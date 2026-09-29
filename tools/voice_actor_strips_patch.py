"""[va-strips] The voice actor panel's profile strips: two roads.

TARGET: app.py

"In the voice actors page, use the random SFX clips thumbs and comfy UI
images to represent the last eight profiles ... tap ... assign ... tap and
hold ... play a sample ... pop up with an audio meter" (2026-09-29).

The strips (desktop/renderer/voice-actor-strips.js) assign through the
panel's existing roads (POST /api/voice-actor/seat, PUT /api/dj/callers/{id});
this tool adds only the two things that did not exist:

  1. GET /api/voice-actor/faces?ids=vl_a,vl_b (read auth) - one picture per
     voice profile: a random SFX VIDEO clip's poster (/api/sfx/poster/{sid},
     signed as the SFX desk signs it) or a random ComfyUI render off the
     /comfy-output mount (/api/generations/image/{name}?w=320, signed "gen:").
     The pick is random ONCE, then kept in data/voice_actor_faces.json, so a
     profile wears the same picture on every screen and every repaint. A
     render that left the mount is re-drawn. Only library voices get a face.
     The SFX draw is a rowid probe of the clip book (sfx_db_reader, never a
     walk of the share); the Comfy pool is one scandir of the mount's top
     folder, held 10 minutes.
  2. POST /api/voice-actor/sample {voice_id} (write auth) - a short sample of
     one profile, for the hold-to-audition popup. NOTHING IS AIRED: it is
     voice_generate's stored clip, the voices desk's own audition road.
     THE ONE-ENGINE RULE (#1209/#1476): it renders on host_clone_engine() and
     on nothing else - the engine is passed explicitly, so neither the #1021
     route-around nor render relief can move it to another engine - and if
     that engine's health says it is not ready the answer is a 409 in words,
     never a render that could wake the other one. The profile's signature
     for that engine is used: the extraction pane's twin capture cut for the
     active engine when the profile has one (provenance.extract.twin_voice),
     and inside the engine voice_ref_for() picks reference_f5.wav on F5 as
     it does on air. fx is None: no performance vector, no strip (the render
     roads' performance_vector / fx["perf"] lines are not touched). The line
     is short and fixed per voice, so a second hold replays from the #821
     sting cache without touching the engine. The answer carries the clip's
     measured level envelope (peak + RMS every 20 ms, read from the stored
     16-bit WAV), which the popup's radial peak-hold meter plays in step with
     the audio - the same numbers on the desk's file: page (no CORS for a
     WebAudio tap) and in the kiosk.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. Needs tools/voice_actor_backend_patch.py first (its
GET /api/voice-actor/state route is the anchor). ON THE HOST.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


_ROUTES_OLD = '@app.get("/api/voice-actor/state")\n'
_ROUTES_NEW = r'''# --- [va-strips] THE PROFILE STRIPS: A FACE PER PROFILE, AND A SAMPLE ON HOLD ---
# The last eight voice profiles ride under every seat of the voice actor panel
# (desktop/renderer/voice-actor-strips.js): tap assigns through the seat roads
# below, hold auditions. The whole account is in tools/voice_actor_strips_patch.py.
VOICE_ACTOR_FACES_PATH = data_path("voice_actor_faces.json")
VOICE_ACTOR_FACES_LOCK = RLock()
VOICE_ACTOR_FACES_MEMO: dict[str, Any] = {"comfy": [], "at": 0.0}
VOICE_ACTOR_FACES_KEEP = 400
VOICE_ACTOR_FACE_SID = re.compile(r"^[a-f0-9]{16}\Z")
VOICE_ACTOR_FACE_NAME = re.compile(r"[\w.\- ()\[\]]{1,200}")
VOICE_ACTOR_FACE_IMAGES = (".png", ".jpg", ".jpeg", ".webp")
VOICE_ACTOR_SAMPLE_LINE = "Hi, this is {name}. This is how I sound on the Pine Box."
VOICE_ACTOR_SAMPLE_STEP_S = 0.02
VOICE_ACTOR_SAMPLE_MAX_S = 30.0


def voice_actor_faces_read() -> dict[str, Any]:
    try:
        raw = json.loads(VOICE_ACTOR_FACES_PATH.read_text("utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 - no store yet is an empty store
        return {}


def voice_actor_faces_save(faces: dict[str, Any]) -> None:
    VOICE_ACTOR_FACES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = VOICE_ACTOR_FACES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(faces, indent=1, sort_keys=True), "utf-8")
    tmp.replace(VOICE_ACTOR_FACES_PATH)


def voice_actor_comfy_pool() -> list[str]:
    """The renders on the /comfy-output mount's top folder: one scandir, held."""
    memo = VOICE_ACTOR_FACES_MEMO
    if memo["at"] and time.time() - float(memo["at"]) < 600:
        return memo["comfy"]
    names: list[str] = []
    try:
        with os.scandir(COMFY_OUTPUT) as it:
            for ent in it:
                if len(names) >= 5000:
                    break
                n = ent.name
                if (n.lower().endswith(VOICE_ACTOR_FACE_IMAGES)
                        and VOICE_ACTOR_FACE_NAME.fullmatch(n) and ent.is_file()):
                    names.append(n)
    except OSError:
        names = []
    memo.update({"comfy": names, "at": time.time()})
    return names


def voice_actor_sfx_draw(rng: Any) -> dict[str, Any] | None:
    """A random VIDEO clip from the clip book (a rowid probe, not a walk)."""
    try:
        con = sfx_db_reader()
        top = con.execute("SELECT MAX(rowid) FROM clips").fetchone()[0]
        for _ in range(6 if top else 0):
            r = con.execute("SELECT sid, name FROM clips WHERE rowid >= ? AND video = 1 AND playable = 1 "
                            "ORDER BY rowid LIMIT 1", (rng.randint(1, int(top)),)).fetchone()
            if r and VOICE_ACTOR_FACE_SID.match(str(r["sid"] or "")):
                return {"kind": "sfx", "ref": str(r["sid"]), "label": str(r["name"] or "")[:80]}
    except Exception:  # noqa: BLE001 - no clip book is no SFX face
        return None
    return None


def voice_actor_face_pick(rng: Any = None) -> dict[str, Any] | None:
    rng = rng or random.Random()
    kinds = ["sfx", "comfy"]
    if rng.random() < 0.5:
        kinds.reverse()
    for kind in kinds:
        if kind == "comfy":
            pool = voice_actor_comfy_pool()
            if pool:
                name = rng.choice(pool)
                return {"kind": "comfy", "ref": name, "label": name[:80], "at": time.time()}
        else:
            got = voice_actor_sfx_draw(rng)
            if got:
                return {**got, "at": time.time()}
    return None


def voice_actor_face_view(face: Any) -> dict[str, Any] | None:
    """A kept face as the strip draws it; the url signed here, used verbatim."""
    if not isinstance(face, dict):
        return None
    kind, ref = str(face.get("kind") or ""), str(face.get("ref") or "")
    if kind == "sfx" and VOICE_ACTOR_FACE_SID.match(ref):
        return {"kind": "sfx", "url": f"/api/sfx/poster/{ref}?t={media_sign(ref)}",
                "label": str(face.get("label") or "")}
    if kind == "comfy" and VOICE_ACTOR_FACE_NAME.fullmatch(ref):
        return {"kind": "comfy", "label": str(face.get("label") or ""),
                "url": f"/api/generations/image/{quote(ref)}?t={media_sign('gen:' + ref)}&w=320"}
    return None


def voice_actor_faces_for(ids: list[str]) -> dict[str, Any]:
    """Each library voice's kept face, drawing (and keeping) one where there
    is none or the render it wore has left the mount. Runs in a thread."""
    known = {str(v.get("id") or "") for v in read_voices()}
    out: dict[str, Any] = {}
    with VOICE_ACTOR_FACES_LOCK:
        faces = voice_actor_faces_read()
        changed = False
        for vid in ids:
            if vid not in known:
                out[vid] = None
                continue
            face = faces.get(vid)
            if isinstance(face, dict) and face.get("kind") == "comfy" \
                    and not (COMFY_OUTPUT / str(face.get("ref") or "")).is_file():
                face = None
            if voice_actor_face_view(face) is None:
                face = voice_actor_face_pick()
                if face:
                    faces[vid] = face
                    changed = True
            out[vid] = voice_actor_face_view(face)
        if changed:
            if len(faces) > VOICE_ACTOR_FACES_KEEP:
                keep = sorted(faces, key=lambda k: -float((faces[k] or {}).get("at") or 0))
                faces = {k: faces[k] for k in keep[:VOICE_ACTOR_FACES_KEEP]}
            voice_actor_faces_save(faces)
    return out


def voice_actor_sample_voice(vid: str, meta: dict[str, Any], engine: str) -> tuple[str, str]:
    """The profile's signature for the ACTIVE engine: its own capture when it
    was cut for that engine (or has no twin), else its twin cut for it."""
    own = str(meta.get("engine") or "").lower()
    if own == engine:
        return vid, ""
    twin = str((((meta.get("provenance") or {}).get("extract")) or {}).get("twin_voice") or "")
    tmeta = voice_meta(twin) if twin else None
    if tmeta and str(tmeta.get("engine") or "").lower() == engine and voice_ref_path(twin) is not None:
        return twin, twin
    return vid, ""


def voice_actor_sample_envelope(media_path: str) -> dict[str, Any] | None:
    """Peak and RMS of the stored take every 20 ms (0..1 of full scale), read
    from the 16-bit WAV itself. None for anything else: the meter then says it
    has no reading rather than drawing one it did not measure."""
    import array
    import math
    import sys as _sys
    f =VOICE_MEDIA_DIR / str(media_path or "").rsplit("/", 1)[-1]
    try:
        with wave.open(str(f), "rb") as w:
            if w.getsampwidth() != 2:
                return None
            rate, chans = w.getframerate(), w.getnchannels()
            raw = w.readframes(int(rate * VOICE_ACTOR_SAMPLE_MAX_S))
    except Exception:  # noqa: BLE001 - not a WAV
        return None
    pcm = array.array("h")
    pcm.frombytes(raw[: len(raw) - len(raw) % 2])
    if _sys.byteorder == "big":
        pcm.byteswap()
    if chans > 1:
        pcm = pcm[::chans]
    step = max(1, int(rate * VOICE_ACTOR_SAMPLE_STEP_S))
    peak: list[float] = []
    rms: list[float] = []
    for i in range(0, len(pcm), step):
        seg = pcm[i:i + step]
        if not seg:
            break
        peak.append(round(max(max(seg), -min(seg)) / 32768.0, 3))
        rms.append(round(math.sqrt(sum(x * x for x in seg) / len(seg)) / 32768.0, 3))
    return {"step_s": VOICE_ACTOR_SAMPLE_STEP_S, "rate": rate, "peak": peak, "rms": rms}


@app.get("/api/voice-actor/faces")
async def voice_actor_faces_api(
    ids: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[va-strips] ?ids=vl_a,vl_b (up to 16) -> {faces: {id: {kind, url, label} | null}}."""
    require_read_auth(authorization)
    want = [v for v in dict.fromkeys(s.strip() for s in str(ids or "").split(","))
            if VOICE_ID_SHAPE.match(v)][:16]
    if not want:
        raise HTTPException(status_code=400, detail="ids: one or more library voice ids")
    return {"faces": await asyncio.to_thread(voice_actor_faces_for, want)}


@app.post("/api/voice-actor/sample")
async def voice_actor_sample_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[va-strips] {voice_id} -> a short sample on the ONE active engine, never aired."""
    require_auth(authorization)
    body = _voice_actor_body_dict(await request.json())
    vid = str(body.get("voice_id") or "")
    meta = await asyncio.to_thread(voice_meta, vid) if VOICE_ID_SHAPE.match(vid) else None
    if not meta:
        raise HTTPException(status_code=404, detail="no such voice in the library")
    engine = host_clone_engine()
    label = "F5" if engine == "f5" else "XTTS"
    health = await (f5_health() if engine == "f5" else xtts_health())
    if not health.get("ready"):
        raise HTTPException(status_code=409, detail=(
            f"{label} is the station's engine and it is not answering yet, so there is no sample. "
            "A sample renders only on the one running engine and never wakes the other (#1476)."))
    use, twin = await asyncio.to_thread(voice_actor_sample_voice, vid, meta, engine)
    if voice_ref_path(use) is None:
        raise HTTPException(status_code=400, detail="this profile has no reference to clone from")
    name = re.sub(r"\s+", " ", str(meta.get("name") or "this voice")).strip()[:40] or "this voice"
    text = VOICE_ACTOR_SAMPLE_LINE.format(name=name)
    made = await voice_generate(text, use, engine)          # engine explicit: no route-around, no relief, no fx
    env = await asyncio.to_thread(voice_actor_sample_envelope, str(made.get("path") or ""))
    ref = voice_ref_for(use, engine) if globals().get("voice_ref_for") else voice_ref_path(use)
    return {"url": f"{made['path']}?t={made['sig']}", "engine": str(made.get("engine") or engine),
            "active": engine, "profile": vid, "voice_id": use, "twin_used": bool(twin),
            "reference": ref.name if ref is not None else "", "cut_for": str(meta.get("engine") or ""),
            "ms": int(made.get("ms") or 0), "seconds": float(made.get("seconds") or 0.0),
            "cached": bool(made.get("cached")), "text": text, "envelope": env, "aired": False}


''' + _ROUTES_OLD

EDITS = [
    ("va-strips-routes", _ROUTES_OLD, _ROUTES_NEW, 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count and "[va-strips] THE PROFILE STRIPS" not in text:
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
