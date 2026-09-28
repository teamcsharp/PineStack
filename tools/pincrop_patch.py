"""[pincrop] The Pine Cam's crop: the station keeps the box, the supervisor cuts it.

"When in full screen mode with the webcam allow me to tap and drag to draw a
crop window that basically reduces the webcam to be that size of window
Cropping out everything around it ... So that way if any event I need to crop
things outside of the camera from showing on the stream that is possible."
(the operator, 2026-09-28)

The picture is cut by tools/pinelink.py in the one ffmpeg every road reads
(see its [pincrop] block). This tool adds the station's half, after
/api/pinelink/announce:

  GET  /api/pinelink/crop            the box asked for (`want`), the box the
                                     running ffmpeg cuts (`applied`, from
                                     state.json's `crop`), `pending` while they
                                     differ, `supervisor_cuts` (false = an old
                                     pinelink.py that cuts nothing), and `say`.
  POST /api/pinelink/crop            {x, y, w, h} fractions of the frame (or
                                     {"crop": {...}}), or {"reset": true} /
                                     {"crop": null}. Keyed. Writes
                                     data/pinelink_crop.json whole, through a
                                     rename; no kick - the supervisor re-reads
                                     it every 2.5 s and restarts only ffmpeg.
  GET  /api/pinelink/crop/frame.jpg  the WHOLE picture to draw on: frame_raw.jpg
                                     while a crop is cut, frame.jpg while none
                                     is. House only - 403 through the public
                                     door and for any tune-in token.

Nothing else in app.py changes: /api/pinelink/state already passes the
supervisor's `crop` block through, and every road (tune page, TS door, HLS,
stills, clips, the phone's lane) reads what the supervisor writes.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST, after wave B1 (it --checks ready on app_b1.py).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


_ROUTES_OLD = '    return {"ok": True, "at": _PINELINK_ANNOUNCE["at"]}\n'
_ROUTES_NEW = r'''    return {"ok": True, "at": _PINELINK_ANNOUNCE["at"]}


# --- [pincrop] THE PINE CAM'S CROP: the box the operator draws --------------
#
# "tap and drag to draw a crop window that basically reduces the webcam to be
#  that size of window Cropping out everything around it ... So that way if
#  any event I need to crop things outside of the camera from showing on the
#  stream that is possible." (the operator, 2026-09-28)
#
# The crop is CUT BY THE SUPERVISOR (tools/pinelink.py), in the encode every
# road reads - the TS door, the house HLS, the stills the tune page polls,
# the phone's lane, the kept clips - so nothing here filters a picture. This
# keeps the box: data/pinelink_crop.json, written whole through a rename (the
# supervisor re-reads it every 2.5 s and must never meet half a file), and
# written by nothing else - pinelink_pref.json has four writers, one of them
# working from a five-second memo, and a privacy setting must not depend on
# all four merging right.
#
# Fractions of the camera frame from its top-left corner, or null. "Saved"
# and "applied" are different claims: `applied` is what the running ffmpeg
# cuts (state.json's `crop`, written by the supervisor), and the page says
# which one is true. The draw mode's picture is the WHOLE frame, served to
# the house only - it is exactly what the crop keeps off the stream.
PINELINK_CROP_PATH = data_path("pinelink_crop.json")
PINELINK_FRAME_RAW = PINELINK_DIR / "frame_raw.jpg"
PINELINK_CROP_MIN = 0.05            # tools/pinelink.py CROP_MIN: a slip, not a box
PINELINK_CROP_FULL = 0.995          # a box this close to the whole frame is no crop
PINELINK_RAW_FRESH_S = 5.0
_PINELINK_LAST_RAW: dict[str, Any] = {"bytes": b"", "at": 0.0, "which": ""}


def pinelink_crop_clean(raw: Any) -> dict[str, float] | None:
    """[pincrop] The box as tools/pinelink.py crop_clean() will read it - the
    same clamp into the frame, the same floor, five places. None is no crop
    (and so is a box that covers the whole frame). ValueError otherwise."""
    import math
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("the crop is not an object")
    try:
        x, y, w, h = (float(raw[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        raise ValueError("the crop needs numbers x, y, w and h") from None
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        raise ValueError("the crop has a number that is not finite")
    x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    w, h = min(w, 1.0 - x), min(h, 1.0 - y)
    if w < PINELINK_CROP_MIN or h < PINELINK_CROP_MIN:
        raise ValueError("that box is under %d%% of the picture on a side - "
                         "draw a bigger one" % round(PINELINK_CROP_MIN * 100))
    if w >= PINELINK_CROP_FULL and h >= PINELINK_CROP_FULL:
        return None
    return {"x": round(x, 5), "y": round(y, 5),
            "w": round(w, 5), "h": round(h, 5)}


def pinelink_crop_read() -> tuple[dict[str, float] | None, str]:
    """[pincrop] (box or None, error): the file as the supervisor reads it."""
    try:
        got = json.loads(PINELINK_CROP_PATH.read_text())
    except FileNotFoundError:
        return None, ""
    except Exception as err:  # noqa: BLE001
        return None, "the crop file cannot be read (%s)" % str(err)[:120]
    try:
        return pinelink_crop_clean(got.get("crop") if isinstance(got, dict)
                                   else "not an object"), ""
    except ValueError as err:
        return None, "the crop file is not a crop (%s)" % err


def pinelink_crop_write(box: dict[str, float] | None, who: str = "") -> None:
    """[pincrop] Whole, through a rename: the supervisor polls this file, and
    an unreadable one keeps the camera on its old cut (or off the air)."""
    PINELINK_CROP_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PINELINK_CROP_PATH.with_name(PINELINK_CROP_PATH.name + ".tmp")
    tmp.write_text(json.dumps({"crop": box, "at": time.time(),
                               "by": str(who or "")[:60]}))
    os.replace(tmp, PINELINK_CROP_PATH)


def _pinelink_crop_same(a: Any, b: Any) -> bool:
    if not a or not b:
        return not a and not b
    try:
        return all(abs(float(a[k]) - float(b[k])) < 1e-4
                   for k in ("x", "y", "w", "h"))
    except Exception:  # noqa: BLE001
        return False


def pinelink_crop_view(say: str = "") -> dict[str, Any]:
    """[pincrop] What is asked for, what is cut, and the sentence between."""
    want, bad = pinelink_crop_read()
    st = pinelink_state()
    cut = st.get("crop") if isinstance(st.get("crop"), dict) else None
    knows = cut is not None
    applied = (cut or {}).get("box") if (cut or {}).get("on") else None
    live = bool(st.get("state") == "live" and st.get("fresh"))
    pending = not _pinelink_crop_same(want, applied)
    err = bad or str((cut or {}).get("error") or "")
    if not say:
        if bad:
            say = (bad + " - the camera keeps the cut it has, or stays off the "
                   "air; set or reset the crop to write it again")
        elif want and not knows:
            say = ("the crop is saved, but the camera link on the host "
                   "(tools/pinelink.py) does not cut crops yet - NOTHING is "
                   "cropped until it is updated and restarted")
        elif pending and live:
            say = "the camera is starting again with the new box - a few seconds"
        elif pending:
            say = "saved - the camera cuts it when it next joins"
        elif applied:
            say = ("cropped: only the box goes out (%d%% x %d%% of the picture)"
                   % (round(applied["w"] * 100), round(applied["h"] * 100)))
        else:
            say = "no crop: the whole picture goes out"
    return {"ok": not bad, "want": want, "applied": applied,
            "pending": pending, "live": live, "supervisor_cuts": knows,
            "state": st.get("state"),
            "source": (cut or {}).get("src") or [848, 480],
            "cut": (cut or {}).get("cut"), "out": (cut or {}).get("out"),
            "pad": (cut or {}).get("pad"), "error": err, "say": say}


@app.get("/api/pinelink/crop")
async def pinelink_crop_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[pincrop] The box asked for, the box being cut, and whether they differ."""
    if request.headers.get("x-pinebox-public") == "1":
        raise HTTPException(status_code=403, detail="the crop is the house's")
    require_read_auth(authorization)
    return await asyncio.to_thread(pinelink_crop_view)


@app.post("/api/pinelink/crop")
async def pinelink_crop_set_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[pincrop] Set the box - {x, y, w, h} as fractions of the frame, or
    {"crop": {...}} - or take it away with {"reset": true} / {"crop": null}.
    No kick: the supervisor sees the file within 2.5 s and restarts only its
    ffmpeg, with the new cut."""
    if request.headers.get("x-pinebox-public") == "1":
        raise HTTPException(status_code=403, detail="the crop is the house's")
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    try:
        if body.get("reset") or ("crop" in body and body.get("crop") is None):
            box = None
        else:
            box = pinelink_crop_clean(body["crop"] if isinstance(body.get("crop"), dict)
                                      else body)
    except ValueError as err:
        view = await asyncio.to_thread(pinelink_crop_view)
        return {**view, "ok": False, "say": str(err)}
    try:
        await asyncio.to_thread(pinelink_crop_write, box, str(body.get("who") or ""))
    except Exception as err:  # noqa: BLE001
        view = await asyncio.to_thread(pinelink_crop_view)
        return {**view, "ok": False,
                "say": "could not keep the crop: " + str(err)[:160]}
    pipeline_log("air", "pine cam crop: %s ([pincrop])" % (
        ("x %.3f y %.3f w %.3f h %.3f" % (box["x"], box["y"], box["w"], box["h"]))
        if box else "none - the whole picture"))
    view = await asyncio.to_thread(pinelink_crop_view)
    if view.get("supervisor_cuts"):
        view["say"] = ("cropped at the camera - it starts again with only the "
                       "box in a few seconds" if box else
                       "the whole picture again - the camera starts again in "
                       "a few seconds")
    return {**view, "ok": True}


def _pinelink_raw_bytes() -> bytes:
    """[pincrop] The whole frame, or b"". While a crop is cut the supervisor
    writes it as frame_raw.jpg; with none, frame.jpg IS the whole frame. Only
    a whole JPEG written since the current cut began is served - a frame
    left over from the previous cut would put the box on the wrong picture."""
    st = pinelink_state()
    cut = st.get("crop") if isinstance(st.get("crop"), dict) else {}
    which = "raw" if cut.get("on") else "frame"
    path = PINELINK_FRAME_RAW if which == "raw" else PINELINK_FRAME
    since = float(cut.get("at") or 0)
    now = time.time()
    raw = b""
    try:
        m = path.stat().st_mtime
        if now - m <= PINELINK_RAW_FRESH_S and m >= since - 1.0:
            raw = path.read_bytes()
    except Exception:  # noqa: BLE001
        raw = b""
    if len(raw) > 1024 and raw[-2:] == b"\xff\xd9":
        _PINELINK_LAST_RAW.update({"bytes": raw, "at": now, "which": which})
        return raw
    if (_PINELINK_LAST_RAW.get("which") == which
            and now - float(_PINELINK_LAST_RAW.get("at") or 0) <= PINELINK_RAW_FRESH_S):
        return bytes(_PINELINK_LAST_RAW.get("bytes") or b"")
    return b""


@app.get("/api/pinelink/crop/frame.jpg")
async def pinelink_crop_frame_api(
    request: Request,
    t: str = "",
    authorization: str | None = Header(default=None),
) -> Response:
    """[pincrop] The WHOLE picture, for drawing the box on. The house only:
    never through the public door, never on a tune-in token - it is the very
    picture the crop keeps off the stream."""
    if request.headers.get("x-pinebox-public") == "1" or t:
        raise HTTPException(status_code=403,
                            detail="the whole picture is for the house only")
    require_read_auth(authorization)
    raw = await asyncio.to_thread(_pinelink_raw_bytes)
    if not raw:
        raise HTTPException(status_code=404,
                            detail="the camera is not sending the whole picture "
                                   "right now")
    return Response(content=raw, media_type="image/jpeg", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Access-Control-Allow-Origin": "*"})
'''

EDITS = [
    ("pincrop-routes", _ROUTES_OLD, _ROUTES_NEW, 1),
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
