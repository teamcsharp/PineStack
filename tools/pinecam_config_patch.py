"""[pinecam-config] the Pine Cam's settings, its recordings, H3, and the album cut.

"if i press and hold on the cam tab show a popup for configuring the pine cam
and its broadcast. offer quality settings, a crop panel, resolution presets,
and wifi adaptor conneciton dropdowns... enable to cam for live and have the
cam export an mp4 to pine box recordings when an album is being cut on a toggle
when the album record is happening (enabled by default). Show any and all
pineCam settings in this popup allowing for adjustment and save the preferences
for reuse and reload. I also want a tab to access previous pine cam recordings
... drag and drop them to the pinebox recordings folder and export footage for
H3 to be used in prompting. For any footage or recording, I want an option to
send it to H3 and have it used as a reference for a stinger."

Answers: the album cut is PineLive's Album recording (the K.O. Sidekick set);
H3 always takes a reference video; the presets change the desk picture and the
recordings (the live feed keeps the camera's own picture).

  app.py       pinelink_cut_span(lo, hi) - the cut route's body, callable
               workshop_source_path("pinecam", name) - a recording as a reference
               /api/pinecam/config GET|POST, /recordings, /thumb/{name},
               /export, /h3, and pinecam_album_cut(row, dest)
  pinelive.py  cut_closed() hands every closed cut to pinecam_album_cut
  pinelink.py  /live.mjpg?fps=&q=&w= - the desk picture's presets, per viewer

Usage (ON THE HOST): python3 tools/pinecam_config_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "[pinecam-config]"

# --------------------------------------------------------------- app.py
CUT_HEAD = '''    def _cut() -> dict[str, Any]:
        import subprocess
'''
CUT_TAIL = '''    got = await asyncio.to_thread(_cut)
'''
CUT_ROUTE_AT = '''@app.post("/api/pinelink/cut")
async def pinelink_cut_api(
'''

SRC_OLD = '''    raise ValueError("Choose a source from the Workshop")


def workshop_reference_video('''
SRC_NEW = '''    if kind == "pinecam":                                             # [pinecam-config]
        path = pinecam_path_of(key)
        if path is None:
            raise FileNotFoundError("That Pine Cam recording is no longer kept")
        return path, "video"
    raise ValueError("Choose a source from the Workshop")


def workshop_reference_video('''

BLOCK_AT = '''@app.get("/api/slideshow/media/{filename}")
'''
BLOCK = r'''# --- [pinecam-config] THE PINE CAM'S SETTINGS, ITS RECORDINGS, H3, THE ALBUM CUT ---
# "if i press and hold on the cam tab show a popup for configuring the pine cam
# and its broadcast ... Show any and all pineCam settings in this popup allowing
# for adjustment and save the preferences for reuse and reload. I also want a tab
# to access previous pine cam recordings ... For any footage or recording, I want
# an option to send it to H3 and have it used as a reference for a stinger."
# Everything is kept in data/pinelink_pref.json (merged, one key at a time) next
# to the keys already there; the radio is data/pinelink_radio.json, which the
# supervisor reads when it starts - so a new adaptor is a restart of the link.
PINECAM_DEFAULTS: dict[str, Any] = {
    "album_mp4": True,          # an mp4 of the cam with every album cut - ON by default
    "desk_fps": 25,             # the desk picture (the MJPEG door): frames a second
    "desk_q": "standard",       #   its JPEG quality
    "desk_w": 0,                #   its width (0 = the camera's own 848)
    "rec_size": "source",       # an exported/album recording: its size ("source" = no re-encode)
    "rec_quality": "standard",  #   its quality when it is re-encoded
}
PINECAM_DESK_FPS = (10, 15, 25, 30)
PINECAM_DESK_Q = {"high": 3, "standard": 5, "low": 9}          # ffmpeg -q:v
PINECAM_DESK_W = (0, 640, 480)
PINECAM_REC_SIZE = {"source": 0, "640": 640, "480": 480}
PINECAM_REC_CRF = {"high": 20, "standard": 24, "small": 28}
PINECAM_EXPORTS = PINELINK_DIR / "exports"
PINECAM_THUMBS = PINELINK_DIR / "thumbs"
PINECAM_ALBUM_LOG = PINELINK_DIR / "album_cuts.jsonl"
PINECAM_RADIO = DATA_DIR / "pinelink_radio.json"
PINECAM_STATION_IF = "wlP9s9"        # holds 10.89.1.246 - never offered
_PINECAM_SEGMENT = re.compile(r"^(\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d)\.mp4$")


def pinecam_config_read() -> dict[str, Any]:
    prefs = pinelink_prefs_read()
    out = dict(PINECAM_DEFAULTS)
    for k in PINECAM_DEFAULTS:
        if k in prefs:
            out[k] = prefs[k]
    out["album_mp4"] = bool(out["album_mp4"])
    if int(out.get("desk_fps") or 0) not in PINECAM_DESK_FPS:
        out["desk_fps"] = PINECAM_DEFAULTS["desk_fps"]
    if out.get("desk_q") not in PINECAM_DESK_Q:
        out["desk_q"] = PINECAM_DEFAULTS["desk_q"]
    if int(out.get("desk_w") or 0) not in PINECAM_DESK_W:
        out["desk_w"] = 0
    if str(out.get("rec_size")) not in PINECAM_REC_SIZE:
        out["rec_size"] = "source"
    if out.get("rec_quality") not in PINECAM_REC_CRF:
        out["rec_quality"] = "standard"
    out["desk_fps"], out["desk_w"], out["rec_size"] = int(out["desk_fps"]), int(out["desk_w"]), str(out["rec_size"])
    return out


def _pinecam_sys(iface: str, name: str) -> str:
    try:
        return (Path("/sys/class/net") / iface / name).read_text().strip()
    except Exception:  # noqa: BLE001
        return ""


def pinecam_adaptors() -> dict[str, Any]:
    """The Wi-Fi radios this box has (the container shares the host's), the one
    the camera link holds now, and the station's own - listed, never offered."""
    try:
        radio = json.loads(PINECAM_RADIO.read_text())
        radio = radio if isinstance(radio, dict) else {}
    except Exception:  # noqa: BLE001
        radio = {}
    try:
        state = json.loads(PINELINK_STATE.read_text())
    except Exception:  # noqa: BLE001
        state = {}
    current = str(radio.get("iface") or state.get("iface") or "")
    rows = []
    try:
        names = sorted(p.name for p in Path("/sys/class/net").iterdir() if p.name.startswith("wl"))
    except Exception:  # noqa: BLE001
        names = []
    for n in names:
        dev = Path("/sys/class/net") / n / "device"
        product = vendor = ""
        try:
            usb = dev.resolve().parent
            product = (usb / "product").read_text().strip() if (usb / "product").is_file() else ""
            vendor = (usb / "idVendor").read_text().strip() if (usb / "idVendor").is_file() else ""
        except Exception:  # noqa: BLE001
            pass
        rows.append({"iface": n, "state": _pinecam_sys(n, "operstate") or "unknown",
                     "mac": _pinecam_sys(n, "address"), "product": product, "vendor": vendor,
                     "station": n == PINECAM_STATION_IF, "current": n == current,
                     "note": (str(radio.get("note") or "") if n == current else "")})
    return {"current": current, "adaptors": rows, "camera": str(state.get("ssid") or ""),
            "signal": state.get("signal")}


def pinecam_export_dest() -> str:
    """Where a recording is carried: the Pine Cam's own export folder, else the
    station's desk folder (PineBoxRecordings) - in the PineCam folder under it."""
    raw = str(pinelink_prefs_read().get("export_dir") or "") or export_desk_dir()
    base = export_dir_windows(raw)
    return (base.rstrip("\\") + "\\PineCam") if base else ""


def pinecam_path_of(name: str) -> Path | None:
    """A recording by its name: the kept clips, then the cuts, then the exports."""
    if not PINELINK_NAME.match(str(name or "")) or ".." in str(name):
        return None
    for folder in (pinelink_clips_dir(), PINELINK_CUTS, PINECAM_EXPORTS):
        p = folder / name
        if p.is_file():
            return p
    return None


def _pinecam_at(p: Path) -> float:
    m = _PINECAM_SEGMENT.match(p.name)
    if m:
        try:
            from datetime import datetime as _dt
            return _dt.strptime(m.group(1), "%Y-%m-%d_%H-%M-%S").timestamp()
        except Exception:  # noqa: BLE001
            pass
    m2 = re.match(r"^cut_(\d{9,11})_\d+\.mp4$", p.name) or re.match(r"^album_.*_(\d{9,11})\.mp4$", p.name)
    if m2:
        return float(m2.group(1))
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def pinecam_recordings() -> dict[str, Any]:
    """Every recording the Spark keeps, newest first: the five-minute footage,
    the ones kept from the box's record button, the cuts, and the album cuts'
    mp4s. The segment still being written is marked: it cannot be read yet."""
    items: list[dict[str, Any]] = []
    now = time.time()
    clips = pinelink_clips_dir()
    segs = []
    try:
        segs = sorted((p for p in clips.glob("*.mp4") if p.is_file()), key=_pinecam_at, reverse=True)[:600]
    except Exception:  # noqa: BLE001
        segs = []
    newest_seg = next((p.name for p in segs if _PINECAM_SEGMENT.match(p.name)), "")
    for p in segs:
        try:
            st = p.stat()
        except OSError:
            continue
        seg = bool(_PINECAM_SEGMENT.match(p.name))
        items.append({"name": p.name, "kind": "footage" if seg else "kept", "at": _pinecam_at(p),
                      "bytes": st.st_size, "url": "/api/pinelink/clip/" + p.name,
                      "writing": bool(seg and p.name == newest_seg and now - st.st_mtime < 30),
                      "host_path": share_path_of(p)})
    try:
        cuts = sorted((p for p in PINELINK_CUTS.glob("*.mp4") if p.is_file()), key=_pinecam_at, reverse=True)[:300]
    except Exception:  # noqa: BLE001
        cuts = []
    for p in cuts:
        try:
            st = p.stat()
        except OSError:
            continue
        items.append({"name": p.name, "kind": "album" if p.name.startswith("album_") else "cut",
                      "at": _pinecam_at(p), "bytes": st.st_size, "url": "/api/pinelink/cut/" + p.name,
                      "writing": False, "host_path": share_path_of(p)})
    items.sort(key=lambda r: r["at"], reverse=True)
    return {"items": items, "count": len(items), "dest": pinecam_export_dest(),
            "clips_host": share_path_of(clips)}


def pinecam_thumb(name: str) -> Path | None:
    src = pinecam_path_of(name)
    if src is None:
        return None
    PINECAM_THUMBS.mkdir(parents=True, exist_ok=True)
    out = PINECAM_THUMBS / (Path(name).stem + ".jpg")
    if out.is_file() and out.stat().st_size > 0:
        return out
    import subprocess
    for at in ("1", "0"):
        try:
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                            "-ss", at, "-i", str(src), "-frames:v", "1", "-vf", "scale=240:-2",
                            "-q:v", "5", str(out)], capture_output=True, timeout=30)
        except Exception:  # noqa: BLE001
            pass
        if out.is_file() and out.stat().st_size > 0:
            return out
    return None


def pinecam_encode(src: Path, tag: str = "") -> Path:
    """A recording in the recordings preset: the camera's own file when the size
    is "source" (no re-encode, no quality lost); otherwise scaled and re-encoded
    once, into data/pinelink/exports, and reused after that."""
    cfg = pinecam_config_read()
    w = PINECAM_REC_SIZE.get(cfg["rec_size"], 0)
    if not w:
        return src
    crf = PINECAM_REC_CRF.get(cfg["rec_quality"], 24)
    PINECAM_EXPORTS.mkdir(parents=True, exist_ok=True)
    out = PINECAM_EXPORTS / ("%s%s_%dw_%s.mp4" % (tag, src.stem, w, cfg["rec_quality"]))
    if out.is_file() and out.stat().st_size > 1024:
        return out
    import subprocess
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(src),
                    "-vf", "scale=%d:-2" % w, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(out)],
                   capture_output=True, timeout=1800)
    if not out.is_file() or out.stat().st_size < 1024:
        raise RuntimeError("the re-encode came out empty")
    return out


def pinecam_config_view(say: str = "") -> dict[str, Any]:
    return {"ok": True, "config": pinecam_config_read(), "radio": pinecam_adaptors(),
            "choices": {"desk_fps": list(PINECAM_DESK_FPS), "desk_q": list(PINECAM_DESK_Q),
                        "desk_w": list(PINECAM_DESK_W), "rec_size": list(PINECAM_REC_SIZE),
                        "rec_quality": list(PINECAM_REC_CRF)},
            "desk_mjpeg": {"fps": pinecam_config_read()["desk_fps"],
                           "q": PINECAM_DESK_Q[pinecam_config_read()["desk_q"]],
                           "w": pinecam_config_read()["desk_w"]},
            "dest": pinecam_export_dest(), "say": say}


@app.get("/api/pinecam/config")
async def pinecam_config_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_read_auth(authorization)
    return await asyncio.to_thread(pinecam_config_view)


@app.post("/api/pinecam/config")
async def pinecam_config_set_api(
    request: Request, authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    patch: dict[str, Any] = {}
    said: list[str] = []
    if "album_mp4" in body:
        patch["album_mp4"] = bool(body.get("album_mp4"))
        said.append("every album cut %s an mp4 of the Pine Cam" % ("brings" if patch["album_mp4"] else "no longer brings"))
    if "desk_fps" in body:
        try:
            v = int(body.get("desk_fps"))
        except (TypeError, ValueError):
            v = 0
        if v not in PINECAM_DESK_FPS:
            return {**pinecam_config_view(), "ok": False, "say": "the desk picture runs at 10, 15, 25 or 30 fps"}
        patch["desk_fps"] = v
        said.append("the desk picture runs at %d fps" % v)
    if "desk_q" in body:
        v = str(body.get("desk_q") or "")
        if v not in PINECAM_DESK_Q:
            return {**pinecam_config_view(), "ok": False, "say": "the desk quality is high, standard or low"}
        patch["desk_q"] = v
        said.append("desk picture quality: " + v)
    if "desk_w" in body:
        try:
            v = int(body.get("desk_w") or 0)
        except (TypeError, ValueError):
            v = -1
        if v not in PINECAM_DESK_W:
            return {**pinecam_config_view(), "ok": False, "say": "the desk picture is the camera's 848, 640 or 480 wide"}
        patch["desk_w"] = v
        said.append("desk picture size: " + ("the camera's own" if not v else "%d wide" % v))
    if "rec_size" in body:
        v = str(body.get("rec_size") or "")
        if v not in PINECAM_REC_SIZE:
            return {**pinecam_config_view(), "ok": False, "say": "a recording is the camera's own size, 640 or 480 wide"}
        patch["rec_size"] = v
        said.append("recordings: " + ("the camera's original" if v == "source" else v + " wide"))
    if "rec_quality" in body:
        v = str(body.get("rec_quality") or "")
        if v not in PINECAM_REC_CRF:
            return {**pinecam_config_view(), "ok": False, "say": "recording quality is high, standard or small"}
        patch["rec_quality"] = v
        said.append("recording quality: " + v)
    if patch:
        try:
            await asyncio.to_thread(pinelink_prefs_write, patch)
        except Exception as err:  # noqa: BLE001
            return {**pinecam_config_view(), "ok": False, "say": "could not remember that: " + str(err)[:160]}
    if "adaptor" in body:
        want = str(body.get("adaptor") or "")
        radios = await asyncio.to_thread(pinecam_adaptors)
        row = next((r for r in radios["adaptors"] if r["iface"] == want), None)
        if row is None or row["station"]:
            return {**pinecam_config_view(), "ok": False,
                    "say": "%s is not a radio the camera can use" % (want[:40] or "that")}
        if not row["current"]:
            try:
                keep = json.loads(PINECAM_RADIO.read_text()) if PINECAM_RADIO.is_file() else {}
                keep = keep if isinstance(keep, dict) else {}
            except Exception:  # noqa: BLE001
                keep = {}
            was = str(keep.get("iface") or "")
            keep.update({"iface": want, "vendor": row["vendor"],
                         "note": "chosen in the Pine Cam settings %s (was %s)%s" % (
                             time.strftime("%Y-%m-%d %H:%M"), was or "the default",
                             (" - " + row["product"]) if row["product"] else "")})
            PINECAM_RADIO.write_text(json.dumps(keep))
            pinelink_kick("connect", "the link restarts on " + want)
            said.append("the camera link restarts on %s%s - about twenty seconds" % (
                want, (" (" + row["product"] + ")") if row["product"] else ""))
    if not said:
        return pinecam_config_view("nothing to change")
    pipeline_log("air", "pine cam settings: " + "; ".join(said) + " [pinecam-config]")
    return pinecam_config_view("; ".join(said))


@app.get("/api/pinecam/recordings")
async def pinecam_recordings_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_read_auth(authorization)
    return await asyncio.to_thread(pinecam_recordings)


@app.get("/api/pinecam/thumb/{name}")
async def pinecam_thumb_api(name: str, authorization: str | None = Header(default=None)) -> Response:
    require_read_auth(authorization)
    got = await asyncio.to_thread(pinecam_thumb, name)
    if got is None:
        raise HTTPException(status_code=404, detail="no picture for that one yet")
    return FileResponse(got, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.post("/api/pinecam/export")
async def pinecam_export_api(
    request: Request, authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Carry one recording to PineBoxRecordings\\PineCam - by the host courier or
    the desk, whichever is there - in the recordings preset."""
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    name = str((body or {}).get("name") or "")
    src = pinecam_path_of(name)
    if src is None:
        return {"ok": False, "say": "that recording is no longer kept"}
    dest = pinecam_export_dest()
    if not dest:
        return {"ok": False, "say": "no export folder is set - name one in the Pine Cam folders"}

    def _go() -> dict[str, Any]:
        path = pinecam_encode(src)
        row = courier_add(path, dest, "pinecam", name=path.name)
        return {"ok": True, "id": row.get("id"), "name": path.name, "dest": dest,
                "say": "%s is on its way to %s" % (path.name, dest)}

    try:
        return await asyncio.to_thread(_go)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "say": "could not export it: %s" % str(exc)[:160]}


@app.post("/api/pinecam/h3")
async def pinecam_h3_api(
    request: Request, authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """A recording as the REFERENCE VIDEO of an H3 stinger ("Always reference
    video"): a 2-5 s window of it, around `at_share`, rides the stinger queue -
    one render at a time, behind the heat and memory gates like every other."""
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    name = str(body.get("name") or "")
    src = pinecam_path_of(name)
    if src is None:
        return {"ok": False, "say": "that recording is no longer kept"}
    prompt = " ".join(str(body.get("prompt") or "").split())[:1200]
    if not prompt:
        return {"ok": False, "say": "say what the stinger should be"}
    try:
        at_share = max(0.0, min(1.0, float(body.get("at_share") or 0.5)))
    except (TypeError, ValueError):
        at_share = 0.5

    def _pin() -> str:
        # the reference is pinned: a copy that is not rolled off with the
        # two days of footage while the stinger waits its turn in the queue
        PINECAM_EXPORTS.mkdir(parents=True, exist_ok=True)
        pinned = PINECAM_EXPORTS / ("h3_" + src.name if not src.name.startswith("h3_") else src.name)
        if not pinned.is_file():
            shutil.copy2(src, pinned)
        return pinned.name

    try:
        ref = await asyncio.to_thread(_pin)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "say": "could not keep the reference: %s" % str(exc)[:160]}
    payload = {"purpose": "parody_stinger", "mode": "reference", "source_type": "pinecam",
               "source": ref, "prompt": prompt, "at_share": at_share}
    queued = _parody_stinger_queue().add(payload)
    _parody_stinger_wake.set()
    pipeline_log("gpu", "pine cam -> H3 stinger: %s at %.0f%% queued (%s) [pinecam-config]"
                 % (ref, at_share * 100, queued.get("id")))
    return {"ok": True, "queued": True, "queue_id": queued.get("id"), "reference": ref,
            "say": "queued for H3 - the stinger uses %s as its reference video" % ref}


def _pinecam_log(row: dict[str, Any]) -> None:
    try:
        PINECAM_ALBUM_LOG.parent.mkdir(parents=True, exist_ok=True)
        with PINECAM_ALBUM_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001
        pass


def pinecam_album_cut(row: dict[str, Any], dest: str) -> dict[str, Any]:
    """PineLive closed an album cut (a track of the K.O. Sidekick set): cut the
    Pine Cam footage of the same span into an mp4 and carry it to the set's own
    folder in PineBoxRecordings beside the track. Runs on its own thread.

    The kept footage is plain mp4 in five-minute segments, readable only once a
    segment is closed - so this waits for the segment after the cut's end to
    begin (at most twelve minutes), then cuts."""
    out = {"event": row.get("event"), "index": row.get("index"), "at": time.time(), "ok": False}
    if not pinecam_config_read()["album_mp4"]:
        out["why"] = "album mp4 is off"
        return out
    try:
        lo = float(row.get("start") or 0)
        hi = lo + float(row.get("seconds") or 0)
    except (TypeError, ValueError):
        lo = hi = 0.0
    if not lo or hi - lo < 1:
        out["why"] = "no span"
        _pinecam_log(out)
        return out

    def _closed() -> bool:
        try:
            return any(_pinecam_at(p) > hi for p in pinelink_clips_dir().glob("*.mp4")
                       if _PINECAM_SEGMENT.match(p.name))
        except Exception:  # noqa: BLE001
            return False

    waited = 0.0
    while not _closed() and waited < 720:
        time.sleep(15)
        waited += 15
    parts = []
    t = lo
    while t < hi:
        parts.append((t, min(hi, t + PINELINK_CUT_MOST)))
        t += PINELINK_CUT_MOST
    stem = Path(str(row.get("mix") or row.get("input") or "cut")).stem
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)[:30]
    carried = []
    for k, (a, b) in enumerate(parts):
        got = pinelink_cut_span(a, b)
        if not got.get("ok"):
            out["why"] = str(got.get("say") or "the cut failed")
            continue
        name = "album_%s%s_%d.mp4" % (stem, ("_p%d" % (k + 1)) if len(parts) > 1 else "", int(a))
        name = name[-64:]
        target = PINELINK_CUTS / name
        try:
            os.replace(PINELINK_CUTS / got["name"], target)
        except Exception:  # noqa: BLE001
            target = PINELINK_CUTS / got["name"]
        try:
            path = pinecam_encode(target)
            if dest:
                r = courier_add(path, dest, "pinelive", name=stem + "_pinecam" + (
                    "_p%d" % (k + 1) if len(parts) > 1 else "") + ".mp4")
                carried.append(r.get("id"))
            out.update({"ok": True, "name": target.name})
        except Exception as exc:  # noqa: BLE001
            out["why"] = "could not carry it: %s" % str(exc)[:160]
    out.update({"courier": carried, "seconds": round(hi - lo, 1), "waited": waited, "dest": dest})
    _pinecam_log(out)
    pipeline_log("air", "pine cam: album cut %s %s (%s) [pinecam-config]" % (
        row.get("index"), "carried as mp4" if carried else "not carried", out.get("why") or dest))
    return out


'''

APP = [
    (SRC_OLD, SRC_NEW, 1),
    (BLOCK_AT, BLOCK + BLOCK_AT, 1),
]

# --------------------------------------------------------------- pinelive.py
PL_OLD = '''        self.note("cut", "cut %d closed: %s + %s (%.1f s)" % (
            row["index"], row["input"], row["mix"], row["seconds"]))
'''
PL_NEW = '''        self.note("cut", "cut %d closed: %s + %s (%.1f s)" % (
            row["index"], row["input"], row["mix"], row["seconds"]))
        # [pinecam-config] "have the cam export an mp4 to pine box recordings
        # when an album is being cut": the Pine Cam's footage of the same span
        # goes to the set's own folder, beside the track (on by default)
        hook = _app("pinecam_album_cut")
        if callable(hook):
            try:
                dest = self.dest_folder(str(row.get("folder") or ""))
            except Exception:  # noqa: BLE001
                dest = ""
            threading.Thread(target=hook, args=(dict(row), dest), name="pinecam-album", daemon=True).start()
'''

# --------------------------------------------------------------- pinelink.py
LK_OLD = '''        addr = (list(door.addrs) or ["127.0.0.1"])[0]
        src = "http://%s:%d/live.ts" % (addr, door.port)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
               "-fflags", "nobuffer", "-flags", "low_delay", "-probesize", "500000",
               "-analyzeduration", "0", "-i", src, "-an",
               "-vf", "fps=%d" % MJPEG_FPS, "-q:v", str(MJPEG_Q),
'''
LK_NEW = '''        addr = (list(door.addrs) or ["127.0.0.1"])[0]
        src = "http://%s:%d/live.ts" % (addr, door.port)
        # [pinecam-config] the desk picture's presets ride the viewer's own URL
        # (?fps=&q=&w=), clamped here; nothing else changes for anyone else
        from urllib.parse import parse_qs, urlsplit
        qs = parse_qs(urlsplit(self.path).query)

        def _num(key: str, lo: int, hi: int, dflt: int) -> int:
            try:
                return max(lo, min(hi, int((qs.get(key) or [dflt])[0])))
            except (TypeError, ValueError):
                return dflt

        fps, qv, width = _num("fps", 5, 30, MJPEG_FPS), _num("q", 2, 31, MJPEG_Q), _num("w", 0, 1280, 0)
        vf = "fps=%d" % fps + ((",scale=%d:-2" % width) if width >= 160 else "")
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
               "-fflags", "nobuffer", "-flags", "low_delay", "-probesize", "500000",
               "-analyzeduration", "0", "-i", src, "-an",
               "-vf", vf, "-q:v", str(qv),
'''


def refactor_cut(src: str) -> str:
    """The cut route's _cut() becomes pinelink_cut_span(lo, hi), a module-level
    function the album hook can call; the route calls it the same way."""
    r = src.index(CUT_ROUTE_AT)
    h = src.index(CUT_HEAD, r)
    t = src.index(CUT_TAIL, h)
    body = src[h:t]
    lines = body.splitlines(True)
    assert lines[0].strip() == "def _cut() -> dict[str, Any]:"
    fn = ["def pinelink_cut_span(lo: float, hi: float) -> dict[str, Any]:\n",
          '    """[pinecam-config] cut [lo, hi] (epoch seconds) out of the kept footage - the\n',
          '    /api/pinelink/cut route\'s own body, callable from the album hook."""\n']
    for ln in lines[1:]:
        fn.append(ln[4:] if ln.startswith("    ") else ln)
    while fn and not fn[-1].strip():
        fn.pop()
    new_fn = "".join(fn) + "\n\n\n"
    out = src[:r] + new_fn + src[r:h] + "    got = await asyncio.to_thread(pinelink_cut_span, lo, hi)\n" + src[t + len(CUT_TAIL):]
    return out


def patch(path, mode, edits, pre=None, py=True):
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = pre(src) if pre else src
    for old, new, n in edits:
        got = out.count(old)
        assert got == n, "%s: %r found %d, want %d" % (path, old[:60], got, n)
        out = out.replace(old, new)
    if py:
        ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/%s.bak-pinecam-config" % os.path.basename(path))
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    mode = sys.argv[1]
    patch(ROOT + "/app.py", mode, APP, pre=refactor_cut)
    patch(ROOT + "/pinelive.py", mode, [(PL_OLD, PL_NEW, 1)])
    patch(ROOT + "/tools/pinelink.py", mode, [(LK_OLD, LK_NEW, 1)])
