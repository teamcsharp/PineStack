#!/usr/bin/env python3
"""[tune-messenger] System 3's Messenger on the public listener page.

"on the tailscale radio station, I want the conversation feed animation like
 we have the messenger tab. It is showing progress. I want users on the
 tailscale using the same version with the most current line assembling the
 same way" (operator, 2026-09-28)

Three edits to app.py; the rest is new files that ship beside it:

  tune_messenger.py              the trimming, the per-round cache, the single
                                 flight and the compressing file server (pure,
                                 tested without app.py)
  frontend/tune-messenger.js     the tune page's Messenger: mounts
                                 system3.js mountEmbedded, answers its paths out
                                 of the snapshot, drives live()/clock() from the
                                 page's own playhead
  tests/test_tune_messenger.py       (local)
  tests/test_tune_messenger_app.py   (imports app: run in the container)

  public-door    GET-only additions to the listener door's allowlist: the
                 snapshot road, its three files, the strict poster road
  routes         /api/system3/public/messenger (tune-in token),
                 /api/system3/public/poster/{sid} (the clip's HMAC, no read-auth
                 fall-through), /tune-messenger/{name} (three named files,
                 ETag + 304 + gzip)
  tune-page      one deferred <script> after the car diagnostics

Contract: --check exits 0 (ready), 2 (applied) or 1 (anchors missing, named);
--apply is idempotent, asserts every anchor count, parses the result, and
writes LF only, atomically. Every anchor is unique in app.py (sha1
5b5d8038114b) and is not inside another tool's stored text in tools/*.py.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

TARGET = "app.py"
MARK = "[tune-messenger]"

PUBLIC_DOOR_OLD = '''def _public_allows(method: str, path: str) -> bool:
'''
PUBLIC_DOOR_NEW = '''# [tune-messenger] System 3's Messenger on the tune page (tune_messenger.py,
# frontend/tune-messenger.js). Named exactly, GET only:
#   /api/system3/public/messenger   ONE trimmed, read-only snapshot behind the
#                                   tune-in token - the words of a turn only
#                                   once it is on the air, never a prompt,
#                                   sheet, direction, setting or seed;
#   /tune-messenger/<three files>   the page's module and System 3's own
#                                   system3.js / system3.css, revalidated and
#                                   compressed (the route serves those names
#                                   and nothing else);
#   /api/system3/public/poster/     a board clip's first frame: the route
#                                   demands the clip's HMAC and, unlike
#                                   /api/sfx/poster, never falls through to a
#                                   read that is open while reads are unlocked.
_PUBLIC_GET |= {"/api/system3/public/messenger",
                "/tune-messenger/tune-messenger.js",
                "/tune-messenger/system3.js",
                "/tune-messenger/system3.css"}
_PUBLIC_GET_PREFIX = _PUBLIC_GET_PREFIX + ("/api/system3/public/poster/",)


def _public_allows(method: str, path: str) -> bool:
'''

ROUTES_OLD = '''    return FileResponse(_CAR_DIAG_JS, media_type="application/javascript",
                        headers={"Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff"})
'''
ROUTES_NEW = ROUTES_OLD + r'''

# --- [tune-messenger] THE MESSENGER ON THE LISTENER DOOR ---------------------
# "on the tailscale radio station, I want the conversation feed animation like
#  we have the messenger tab ... users on the tailscale using the same version
#  with the most current line assembling the same way" (operator, 2026-09-28)
#
# The tune page mounts System 3's own Messenger (frontend/system3.js
# mountEmbedded) through frontend/tune-messenger.js, which answers every path
# the Messenger asks for out of ONE snapshot polled from here. What a listener
# may see, the per-round cache and the single flight are tune_messenger.py
# (tested without this file); this is the wiring: the tune-in token, the rings
# read on the loop, System 3's store read on its own reader thread.
try:
    import tune_messenger as _tune_messenger
    _TUNE_MSG = _tune_messenger.PublicMessenger()
    _TUNE_MSG_FILES = _tune_messenger.StaticFiles({
        "tune-messenger.js": Path(__file__).resolve().parent / "frontend" / "tune-messenger.js",
        "system3.js": Path(__file__).resolve().parent / "frontend" / "system3.js",
        "system3.css": Path(__file__).resolve().parent / "frontend" / "system3.css"})
except Exception as _tune_msg_exc:  # noqa: BLE001
    _tune_messenger = None
    _TUNE_MSG = None
    _TUNE_MSG_FILES = None
    print("[tune-messenger] not installed: %s: %s"
          % (type(_tune_msg_exc).__name__, _tune_msg_exc), flush=True)


def _tune_msg_gzip(request: Request) -> bool:
    return "gzip" in str(request.headers.get("accept-encoding") or "").lower()


@app.get("/api/system3/public/messenger")
async def tune_messenger_api(
    request: Request,
    t: str = "",
    have: str = "",
    authorization: str | None = Header(default=None),
) -> Response:
    """[tune-messenger] The listener's Messenger: the rounds the air is on
    and the ones planned after them, trimmed by tune_messenger.py. Tune-in
    token only. At most one build every 2.5 s however many listeners ask,
    and each answer carries only the rounds whose revision the page does
    not already hold (`have` = "cid:rev,...")."""
    require_listen_auth(t, authorization)
    if _TUNE_MSG is None:
        raise HTTPException(status_code=404, detail="the Messenger is not installed")
    gz = _tune_msg_gzip(request)
    runtime = globals().get("_system3")
    try:
        rt = runtime() if callable(runtime) else None
    except Exception:  # noqa: BLE001
        rt = None
    if rt is None or not getattr(rt, "ready", False) or getattr(rt, "store", None) is None:
        body, headers = _TUNE_MSG.answer(have, gz, off=True)
        return Response(content=body, media_type="application/json", headers=headers)
    if _TUNE_MSG.stale():
        try:
            # Copied here, on the loop, so the reader thread never walks a
            # ring the station is appending to.
            air = _tune_messenger.air_index(list(_RADIO.get("voice_clips") or [])[-400:],
                                            VOICE_BROADCAST_LEAD_MS)
            chat = _tune_messenger.chat_index(list(_RADIO.get("chat") or [])[-400:],
                                              AIR_PUBLICATION_STATES, line_heard_at)
            stamps = {k: dict(v) for k, v in list(_S3_LINE_BY_ID.items())[-600:]
                      if isinstance(v, dict)}
            await _TUNE_MSG.refresh(rt.read, rt.store, air, chat, stamps, media_sign)
        except Exception as exc:  # noqa: BLE001
            # The last good snapshot still answers; the page asks again.
            print("[tune-messenger] the snapshot was not rebuilt: %s: %s"
                  % (type(exc).__name__, exc), flush=True)
    body, headers = _TUNE_MSG.answer(have, gz)
    return Response(content=body, media_type="application/json", headers=headers)


@app.get("/api/system3/public/poster/{sid}")
async def tune_messenger_poster(sid: str, request: Request, t: str = "") -> Response:
    """[tune-messenger] A board clip's first frame for the listener's
    Messenger. /api/sfx/poster falls through to require_read_auth - open
    while reads are unlocked - so it is not on the door; this road answers
    only the clip's own HMAC, and then draws the same poster."""
    want = media_sign(sid) if re.fullmatch(r"[a-f0-9]{16}", str(sid or "")) else ""
    if not (want and t and hmac.compare_digest(str(t), want)):
        return Response(status_code=404)
    return await sfx_poster_api(sid, request, authorization=None)


@app.get("/tune-messenger/{name}")
async def tune_messenger_file(name: str, request: Request) -> Response:
    """[tune-messenger] The tune page's module and System 3's own
    system3.js / system3.css, the three names and nothing else: an ETag and
    a 304 (FileResponse has neither - /system3/system3.js is 441 kB on every
    load) and gzip when the phone takes it (130 kB). Public code, like the
    page."""
    if _TUNE_MSG_FILES is None:
        return Response(status_code=404)
    status, body, headers = await asyncio.to_thread(
        _TUNE_MSG_FILES.respond, str(name or ""),
        str(request.headers.get("if-none-match") or ""), _tune_msg_gzip(request))
    if status == 404:
        return Response(status_code=404)
    return Response(content=body, status_code=status, headers=headers)
'''

PAGE_OLD = '''<script src="__CAR_DIAG_SRC__" defer></script>
'''
PAGE_NEW = PAGE_OLD + '''<!-- [tune-messenger] System 3's Messenger in place of the feed below the
     controls (a switch keeps the feed): the conversation assembling message
     by message, in step with the line this page is sounding. Deferred and
     last, like the diagnostics: a module that fails leaves the page and its
     feed exactly as they were. -->
<script src="/tune-messenger/tune-messenger.js" defer></script>
'''

# (name, old, new, count)
EDITS = [
    ("public-door", PUBLIC_DOOR_OLD, PUBLIC_DOOR_NEW, 1),
    ("routes", ROUTES_OLD, ROUTES_NEW, 1),
    ("tune-page", PAGE_OLD, PAGE_NEW, 1),
]


def read(path: Path) -> str:
    text = path.read_bytes().decode("utf-8")
    if "\r\n" in text:
        print("note: %s had CRLF line endings; they are written back as LF" % path)
        text = text.replace("\r\n", "\n")
    return text


def state(text: str) -> tuple[list[str], list[str], list[str]]:
    ready, applied, missing = [], [], []
    for name, old, new, count in EDITS:
        if text.count(new) == count:
            applied.append(name)
        elif text.count(old) == count:
            ready.append(name)
        else:
            missing.append("%s (anchor found %d times, expected %d)" % (name, text.count(old), count))
    return ready, applied, missing


def check(path: Path) -> int:
    ready, applied, missing = state(read(path))
    if missing:
        print("MISSING: " + "; ".join(missing))
        return 1
    if not ready:
        print("APPLIED: " + ", ".join(applied))
        return 2
    print("READY: " + ", ".join(ready) + ("" if not applied else "  (already applied: " + ", ".join(applied) + ")"))
    return 0


def apply(path: Path) -> int:
    text = read(path)
    ready, applied, missing = state(text)
    if missing:
        print("MISSING: " + "; ".join(missing) + " - nothing written")
        return 1
    if not ready:
        print("APPLIED already: " + ", ".join(applied))
        return 0
    for name, old, new, count in EDITS:
        if name not in ready:
            continue
        assert text.count(old) == count, name
        text = text.replace(old, new, count)
        assert text.count(new) == count, name + " did not land"
    try:
        ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        print("REFUSED: the patched file does not parse: %s" % exc)
        return 1
    fd, tmp = tempfile.mkstemp(prefix=".tune_messenger.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(text.encode("utf-8"))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    print("APPLIED: " + ", ".join(ready))
    return 0


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = [a for a in argv[1:] if a.startswith("--")]
    path = Path(args[0]) if args else Path(__file__).resolve().parent.parent / TARGET
    if not path.is_file():
        print("no such file: %s" % path)
        return 1
    if "--apply" in flags:
        return apply(path)
    return check(path)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
