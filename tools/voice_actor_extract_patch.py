"""[voice-actor-extract] The signature-making pane's roads.

TARGET: app.py

"I also want to be able to put youtube links in the window and drag in and
out points and set the specifics of video for the audio to be extracted as a
sample for an audio XTTS / F5 cloned template ... load mp3s, mp4s from the
SFX library ... search and scroll through folders and preview mp4s and mp3s
and put those in a bin cart so they can be used in conjunction for a voice
signature ... multiple SFX clips to generate one signature if the single clip
is too short ... extract audio and convert it to an actor from the sfx/user
directory of user submitted video to make videos and ads from the submitted
content." (the operator, 2026-09-28)

The pane (desktop/renderer/voice-actor-extract.js) drives the Voice Studio's
own pipeline - the voice lab's /ingest, _voicelab_start, the harvest that
rides GET /api/voicelab/jobs/{id}, the #1476 capture cut per engine - and this
tool adds only what did not exist:

  1. THE CART ROAD. No road took several clips as ONE job: /api/voices/merge
     joins voices that each survived the lab alone, and a clip too short to
     survive alone (the reason for a cart) never gets that far. So the cart's
     clips are cut (each to its own in/out) and joined HERE, on the station,
     into one 24 kHz mono wav with a short silence between them, and that one
     file goes to the lab's /ingest exactly as /api/voicelab/upload sends an
     upload. The lab then runs its whole pipeline once (transcribe, diarize,
     signature, the reference cut for the engine). The join is a stage of its
     own ("join", on the station) and is reported as one; nothing is copied
     anywhere that lasts - the parts live in a temp dir that is gone before
     the lab is called, and the SFX clips themselves are only read.
  2. A LINK WITH ITS SPECIFICS. The same _voicelab_start the studio's link
     card uses, with the in/out the pane's handles set, plus who this is and
     the notes - kept with the job and written onto the voice when it lands.
  3. THE CLIP BOOK, BROWSED. /api/sfx/folders shows three clips a folder;
     /api/sfx/dir lists one with iterdir ON THE LOOP over CIFS. This reads the
     clip book (data/sfx_clips.db, the pick's own read connection) off the
     loop: one folder page by a primary-key range, or a search through the
     house's one postings list (sfx_match_score - names, what is said, what is
     seen, senses) when it is built, else names and transcripts by LIKE.
     Signed url / poster_url / spec_url exactly as the SFX desk signs them.
  4. LISTENER UPLOADS ARE MARKED. A clip under samples_grabbed/user (where the
     upload courier delivers) is flagged user-submitted, and the voice made
     from it carries source.user_submitted plus a credit read from the file
     name the courier gave it (<date>_<time>_<who>_<name>) - so an ad or a
     video made with that actor can credit the source.
  5. ONE LEDGER, data/voice_actor_extract.json. Each submission is a vx_ id
     the pane polls; the poll proxies voicelab_job() itself (so the harvest
     still happens exactly there) and, once harvested, stamps the voice's
     meta: source (url + range, or the clips), provenance.extract (who,
     notes, the join, the twin capture for the other engine). A station
     restart mid-join says so (STATION_RESTARTED); retry re-runs from the
     kept inputs.

Routes: GET /api/voice-actor/extract/health, GET /api/voice-actor/extract/sfx,
POST /api/voice-actor/extract/link, POST /api/voice-actor/extract/clips,
GET /api/voice-actor/extract/jobs, GET /api/voice-actor/extract/jobs/{vx},
POST /api/voice-actor/extract/jobs/{vx}/retry. None renders speech, none
touches a level, a seat or the engine. (The harvest these ride is the
pipeline's own and unchanged - it still warms XTTS latents as it always has.)

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST. Independent of tools/voice_actor_backend_patch.py
(either order).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


_ROUTES_OLD = '@app.post("/api/voicelab/chapters")\n'
_ROUTES_NEW = r'''# --- [voice-actor-extract] THE SIGNATURE-MAKING PANE: CART JOIN, LINK SPECIFICS, CLIP BOOK BROWSE ---
# The voice actor subpanel's "New actor" layer (desktop/renderer/
# voice-actor-extract.js). Everything here rides the Voice Studio's pipeline:
# the lab's /ingest, _voicelab_start, the harvest on GET /api/voicelab/jobs/{id}
# (voicelab_job, called as it is) and the #1476 cut per engine. New: a cart of
# clips joined on the station into ONE lab job, a link's specifics kept and
# written onto the voice, the clip book browsed off the loop, and listener
# uploads (samples_grabbed/user) marked user-submitted with a credit. The whole
# account is in tools/voice_actor_extract_patch.py.
VOICE_ACTOR_X_PATH = data_path("voice_actor_extract.json")
VOICE_ACTOR_X_LOCK = RLock()
VOICE_ACTOR_X_MEMO: dict[str, Any] = {"book": None}
VOICE_ACTOR_X_TASKS: dict[str, Any] = {}          # vx -> the station-side task while it runs
VOICE_ACTOR_X_ID = re.compile(r"^vx_[a-f0-9]{10}\Z")
VOICE_ACTOR_X_SID = re.compile(r"^[a-f0-9]{16}\Z")
VOICE_ACTOR_X_KEEP = 200
VOICE_ACTOR_X_CLIPS_MAX = 12                      # the merge road's own ceiling
VOICE_ACTOR_X_JOIN_MOST_S = 900.0                 # one lab job, CPU whisper: keep it a sample
VOICE_ACTOR_X_JOIN_LEAST_S = 3.0                  # under this whisper has nothing to hear
VOICE_ACTOR_X_GAP_S = 0.4                         # silence between joined clips
VOICE_ACTOR_X_CLIP_BYTES = 300 * 1024 * 1024
VOICE_ACTOR_X_RATE = 24000                        # what the lab converts to anyway
VOICE_ACTOR_X_USER = ("samples_grabbed", "user")  # the upload courier's folder on the share
VOICE_ACTOR_X_STAGES = ("download", "extract_audio", "transcribe", "diarize",
                        "analyze_pitch", "analyze_cadence", "build_signature",
                        "extract_reference", "cleanup")   # voice-lab STAGES, mirrored
_VOICE_ACTOR_X_WHO = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})_([^_]+)_(.+)$")


def voice_actor_x_read() -> dict[str, Any]:
    with VOICE_ACTOR_X_LOCK:
        if VOICE_ACTOR_X_MEMO["book"] is None:
            book: dict[str, Any] = {"jobs": {}}
            try:
                got = json.loads(VOICE_ACTOR_X_PATH.read_text())
                if isinstance(got, dict) and isinstance(got.get("jobs"), dict):
                    book = {"jobs": got["jobs"]}
            except Exception:  # noqa: BLE001 - a missing or torn ledger starts empty
                pass
            VOICE_ACTOR_X_MEMO["book"] = book
        return VOICE_ACTOR_X_MEMO["book"]


def voice_actor_x_save() -> None:
    with VOICE_ACTOR_X_LOCK:
        jobs = voice_actor_x_read()["jobs"]
        if len(jobs) > VOICE_ACTOR_X_KEEP:
            for old in sorted(jobs, key=lambda k: float(jobs[k].get("created") or 0))[:len(jobs) - VOICE_ACTOR_X_KEEP]:
                jobs.pop(old, None)
        try:
            VOICE_ACTOR_X_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = VOICE_ACTOR_X_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps({"jobs": jobs}))
            tmp.replace(VOICE_ACTOR_X_PATH)
        except Exception as exc:  # noqa: BLE001
            pipeline_log("voice", f"[voice-actor-extract] ledger not written: {exc}"[:200])


def voice_actor_x_row(vx: str) -> dict[str, Any] | None:
    with VOICE_ACTOR_X_LOCK:
        row = voice_actor_x_read()["jobs"].get(vx)
        return json.loads(json.dumps(row)) if isinstance(row, dict) else None


def voice_actor_x_update(vx: str, save: bool = True, **fields: Any) -> None:
    with VOICE_ACTOR_X_LOCK:
        row = voice_actor_x_read()["jobs"].get(vx)
        if not isinstance(row, dict):
            return
        row.update(fields)
        row["updated"] = time.time()
        if save:
            voice_actor_x_save()


def voice_actor_x_user_root() -> str:
    return SFX_ROOT.joinpath(*VOICE_ACTOR_X_USER).as_posix()


def voice_actor_x_is_user(path: Any) -> bool:
    """A clip the listener courier delivered (samples_grabbed/user)."""
    p = "/" + str(path or "").replace("\\", "/").strip("/").lower() + "/"
    return ("/" + "/".join(VOICE_ACTOR_X_USER) + "/") in p


def voice_actor_x_credit(path: Any) -> dict[str, Any]:
    """Who sent it, as far as the file name the courier gave it says
    (listener_uploads.upload_name: <date>_<time>_<who>_<name>.<ext>)."""
    name = Path(str(path or "")).name
    got = _VOICE_ACTOR_X_WHO.match(name)
    if not got:
        return {"file": name, "who": "", "sent": "",
                "from": "a listener upload (the file name carries no sender)"}
    return {"file": name, "who": got.group(5)[:40],
            "sent": "%s %s:%s" % (got.group(1), got.group(2), got.group(3)),
            "from": "the name the upload courier gave the file"}


def voice_actor_x_where(path: Any) -> str:
    raw = str(path or "")
    for root, label in ((SFX_ROOT, "samples"), (SFX_LOCAL_ROOT, "station samples")):
        try:
            return "%s/%s" % (label, Path(raw).relative_to(root))
        except Exception:  # noqa: BLE001
            continue
    return raw


def voice_actor_x_clip(r: Any) -> dict[str, Any] | None:
    """One clip-book row as the pane draws it; urls signed as the SFX desk
    signs them (the pane uses them verbatim and never builds t=)."""
    sid = str(r["sid"] or "")
    if not VOICE_ACTOR_X_SID.match(sid):
        return None
    path = str(r["path"] or "")
    video = bool(r["video"])
    t = media_sign(sid)
    said = ""
    try:
        said = str(r["said"] or "")[:160]
    except Exception:  # noqa: BLE001 - the column arrives with the first listen
        said = ""
    return {"id": sid, "name": str(r["name"] or Path(path).stem)[:120], "video": video,
            "seconds": round(float(r["seconds"] or 0), 2),
            "folder": path.rsplit("/", 1)[0], "where": voice_actor_x_where(path),
            "url": f"/sfx/{sid}?t={t}",
            "poster_url": f"/api/sfx/poster/{sid}?t={t}" if video else "",
            "spec_url": f"/api/sfx/spec/{sid}?t={t}",
            "user": voice_actor_x_is_user(path), "said": said}


def voice_actor_x_browse(folder: str, q: str, video: str, offset: int, limit: int) -> dict[str, Any]:
    """A page of the clip book: one folder (a primary-key range, never a walk
    of the share) or a search. Runs in a thread."""
    con = sfx_db_reader()
    cols = "rowid, path, sid, name, video, seconds, said"
    vid_sql = {"1": " AND video = 1", "0": " AND video = 0"}.get(video, "")
    vid_flag = {"1": True, "0": False}.get(video)
    if folder == "user":
        folder = voice_actor_x_user_root()
    folder = folder.rstrip("/")
    rows: list[Any] = []
    total = -1
    how = "folder"
    say = ""
    if q:
        if sfx_match_ready():
            how = "index"
            cands = sfx_match_score(q, "", video=vid_flag, limit=min(400, offset + limit + 1))
            ids = [int(c.rowid) for c in list(cands or [])[offset:offset + limit + 1]]
            if ids:
                marks = ",".join("?" * len(ids))
                try:
                    got = con.execute("SELECT %s FROM clips WHERE rowid IN (%s)" % (cols, marks), ids).fetchall()
                except Exception:  # noqa: BLE001
                    got = con.execute("SELECT rowid, path, sid, name, video, seconds FROM clips "
                                      "WHERE rowid IN (%s)" % marks, ids).fetchall()
                by = {int(r["rowid"]): r for r in got}
                rows = [by[i] for i in ids if i in by]
            say = "the clip index: names, what is said, what is seen"
        else:
            how = "names"
            like = "%" + q.replace("%", "").replace("_", "") + "%"
            try:
                rows = con.execute("SELECT %s FROM clips WHERE playable = 1%s AND (name LIKE ? OR said LIKE ?) "
                                   "ORDER BY name LIMIT ? OFFSET ?" % (cols, vid_sql),
                                   (like, like, limit + 1, offset)).fetchall()
            except Exception:  # noqa: BLE001
                rows = con.execute("SELECT rowid, path, sid, name, video, seconds FROM clips WHERE playable = 1%s "
                                   "AND name LIKE ? ORDER BY name LIMIT ? OFFSET ?" % vid_sql,
                                   (like, limit + 1, offset)).fetchall()
            say = "the clip index is still being built - searched names and what is said only"
        if folder:
            rows = [r for r in rows if str(r["path"] or "").startswith(folder + "/")]
    elif folder:
        lo, hi = folder + "/", folder + "0"      # '0' sorts right after '/': the folder's own key range
        where = "path >= ? AND path < ? AND playable = 1 AND instr(substr(path, ?), '/') = 0" + vid_sql
        args = (lo, hi, len(lo) + 1)
        try:
            rows = con.execute("SELECT %s FROM clips WHERE %s ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?"
                               % (cols, where), args + (limit + 1, offset)).fetchall()
        except Exception:  # noqa: BLE001
            rows = con.execute("SELECT rowid, path, sid, name, video, seconds FROM clips WHERE %s "
                               "ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?" % where,
                               args + (limit + 1, offset)).fetchall()
        total = int(con.execute("SELECT COUNT(*) FROM clips WHERE %s" % where, args).fetchone()[0])
    more = len(rows) > limit
    out = [c for c in (voice_actor_x_clip(r) for r in rows[:limit]) if c]
    if folder == voice_actor_x_user_root() and not out and not q:
        say = "nothing from listeners is in the clip book yet (samples_grabbed/user)"
    return {"ok": True, "folder": folder, "q": q, "how": how, "total": total, "offset": offset,
            "clips": out, "more": more, "user_root": voice_actor_x_user_root(), "say": say}


def voice_actor_x_join(vx: str, clips: list[dict[str, Any]]) -> tuple[bytes, dict[str, Any]]:
    """Cut each clip to its own in/out, mono 24 kHz, and join them with a short
    silence: ONE file for ONE lab job. Runs in a thread; parts live in a temp
    dir that is gone before this returns; the clips themselves are only read."""
    import subprocess
    import tempfile
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    nice = ["nice", "-n", "10"] if shutil.which("nice") else []
    parts: list[bytes] = []
    lengths: list[float] = []
    with tempfile.TemporaryDirectory(prefix="vx_") as tmp:
        for i, clip in enumerate(clips):
            voice_actor_x_update(vx, save=False, progress=round(i / max(1, len(clips)), 3),
                                 note="cutting clip %d of %d (%s)" % (i + 1, len(clips), clip.get("name") or ""))
            src = Path(str(clip["path"]))
            if src.stat().st_size > VOICE_ACTOR_X_CLIP_BYTES:
                raise ValueError("%s is over 300 MB - cut it smaller first" % src.name)
            out = Path(tmp) / ("p%02d.wav" % i)
            cmd = nice + [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
            if clip.get("start") is not None:
                cmd += ["-ss", "%.3f" % float(clip["start"])]
            if clip.get("end") is not None:
                cmd += ["-to", "%.3f" % float(clip["end"])]
            cmd += ["-i", str(src), "-vn", "-ac", "1", "-ar", str(VOICE_ACTOR_X_RATE),
                    "-c:a", "pcm_s16le", str(out)]
            run = subprocess.run(cmd, capture_output=True, timeout=300)
            if run.returncode != 0 or not out.is_file():
                raise ValueError("%s would not decode: %s" % (
                    src.name, run.stderr.decode(errors="ignore").strip()[-160:] or "no audio"))
            with wave.open(str(out), "rb") as w:
                frames = w.readframes(w.getnframes())
            if len(frames) < VOICE_ACTOR_X_RATE // 10:      # under 0.05 s: nothing there
                continue
            parts.append(frames)
            lengths.append(len(frames) / 2.0 / VOICE_ACTOR_X_RATE)
    speech = sum(lengths)
    if speech < VOICE_ACTOR_X_JOIN_LEAST_S:
        raise ValueError("the clips hold %.1f s of audio between them - the lab needs more than %.0f s "
                         "(and 10 s of clean speech for a clone that is not rough)" % (speech, VOICE_ACTOR_X_JOIN_LEAST_S))
    if speech > VOICE_ACTOR_X_JOIN_MOST_S:
        raise ValueError("the clips join to %.0f s - one job takes at most %.0f s; trim their in/out points"
                         % (speech, VOICE_ACTOR_X_JOIN_MOST_S))
    gap = b"\x00\x00" * int(VOICE_ACTOR_X_RATE * VOICE_ACTOR_X_GAP_S)
    pcm = gap.join(parts)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(VOICE_ACTOR_X_RATE)
        w.writeframes(pcm)
    joined = {"clips": len(parts), "seconds": round(len(pcm) / 2.0 / VOICE_ACTOR_X_RATE, 1),
              "speech_seconds": round(speech, 1), "gap_s": VOICE_ACTOR_X_GAP_S,
              "lengths": [round(x, 1) for x in lengths]}
    return buf.getvalue(), joined


async def voice_actor_x_run(vx: str) -> None:
    """The station-side part of one submission, then the lab takes over."""
    row = voice_actor_x_row(vx) or {}
    engine = capture_engine(row.get("engine"))
    try:
        if row.get("kind") == "link":
            voice_actor_x_update(vx, stage="handoff", progress=0.0,
                                 note="handing the link to the voice lab")
            body = {"url": str(row.get("url") or ""), "start": row.get("start"), "end": row.get("end"),
                    "speaker": str(row.get("speaker") or ""), "mode": "both"}
            job_id = await _voicelab_start(body, name=str(row.get("name") or ""), engine=engine)
        else:
            voice_actor_x_update(vx, stage="join", progress=0.0, note="joining the cart on the station")
            blob, joined = await asyncio.to_thread(voice_actor_x_join, vx, list(row.get("clips_in") or []))
            voice_actor_x_update(vx, stage="handoff", progress=0.0, joined=joined,
                                 note="sending the joined %.1f s to the voice lab" % joined["seconds"])
            params: dict[str, Any] = {"filename": "cart_%s.wav" % vx, "mode": "both", **capture_params(engine)}
            if row.get("speaker"):
                params["speaker"] = str(row["speaker"])
            try:
                async with httpx.AsyncClient(timeout=300) as client:
                    got = await client.post(f"{VOICE_LAB_URL}/ingest", params=params, content=blob,
                                            headers={"Content-Type": "application/octet-stream"})
            except Exception as exc:
                raise HTTPException(status_code=503, detail="voice-lab is down - is the voice-lab container "
                                                            "running? (docker compose up -d voice-lab)") from exc
            if got.status_code != 200:
                detail = ""
                try:
                    detail = str((got.json() or {}).get("detail") or "")
                except Exception:  # noqa: BLE001
                    detail = got.text[:200]
                raise HTTPException(status_code=502, detail=f"voice-lab refused: {detail}")
            job_id = str((got.json() or {}).get("job_id") or "")
            with _VOICE_JOBS_LOCK:                         # as /api/voicelab/upload registers one
                _VOICE_JOBS[job_id] = {"name": str(row.get("name") or ""), "caller_id": "",
                                       "update_voice": "", "range": "", "started": time.time(),
                                       "engine": engine}
        if not job_id:
            raise HTTPException(status_code=502, detail="voice-lab answered without a job id")
        voice_actor_x_update(vx, state="lab", lab_job=job_id, stage="queued", progress=0.0, note="",
                             error="", error_kind="")
    except HTTPException as exc:
        voice_actor_x_update(vx, state="error", stage="error", error=str(exc.detail)[:300],
                             error_kind="LAB_REFUSED" if exc.status_code == 502 else "LAB_DOWN")
    except Exception as exc:  # noqa: BLE001
        voice_actor_x_update(vx, state="error", stage="error", error=str(exc)[:300], error_kind="JOIN_FAILED")
    finally:
        VOICE_ACTOR_X_TASKS.pop(vx, None)


def voice_actor_x_launch(vx: str) -> None:
    VOICE_ACTOR_X_TASKS[vx] = asyncio.create_task(voice_actor_x_run(vx))


def voice_actor_x_public(row: dict[str, Any]) -> dict[str, Any]:
    """What the pane is told about a submission, beside the lab's own fields."""
    clips = [{k: c.get(k) for k in ("id", "name", "video", "user", "seconds", "start", "end", "where")}
             for c in (row.get("clips_in") or [])]
    return {"vx": row.get("id"), "kind": row.get("kind"), "name": row.get("name") or "",
            "who": row.get("who") or "", "notes": row.get("notes") or "",
            "engine": row.get("engine") or "", "twin": row.get("twin") or "",
            "url": row.get("url") or "", "range": row.get("range") or "",
            "clips": clips, "user_submitted": bool(row.get("user_submitted")),
            "credits": row.get("credits") or [], "joined": row.get("joined"),
            "lab_job": row.get("lab_job") or "", "created": row.get("created") or 0}


def voice_actor_x_stamp(vx: str, row: dict[str, Any], status: dict[str, Any]) -> bool:
    """The harvested voice learns where it came from: source (the link and its
    range, or the clips), user_submitted + credits, and the specifics."""
    vid = str(status.get("voice_id") or "")
    meta = voice_meta(vid) if VOICE_ID_SHAPE.match(vid) else None
    if not meta:
        return False
    if row.get("kind") == "link":
        source = {"type": "url", "url": str(row.get("url") or ""), "range": str(row.get("range") or "")}
    else:
        source = {"type": "sfx", "url": "", "range": "",
                  "clips": [{k: c.get(k) for k in ("id", "name", "where", "start", "end", "user")}
                            for c in (row.get("clips_in") or [])]}
    source["user_submitted"] = bool(row.get("user_submitted"))
    if row.get("credits"):
        source["credit"] = row["credits"]
    twin = voice_actor_x_row(str(row.get("twin") or "")) or {}
    prov = dict(meta.get("provenance") or {})
    prov["extract"] = {"road": "voice actor extraction pane", "vx": vx, "lab_job": row.get("lab_job") or "",
                       "who": row.get("who") or "", "notes": row.get("notes") or "",
                       "engine": row.get("engine") or "", "joined": row.get("joined"),
                       "twin": row.get("twin") or "", "twin_voice": twin.get("voice_id") or "",
                       "at": time.time()}
    meta["source"] = source
    meta["provenance"] = prov
    if row.get("name"):
        meta["name"] = str(row["name"])[:80]
    voice_save(meta)
    if twin.get("voice_id"):                              # the other engine's capture learns its twin
        other = voice_meta(str(twin["voice_id"]))
        if other:
            oprov = dict(other.get("provenance") or {})
            ext = dict(oprov.get("extract") or {})
            ext["twin_voice"] = vid
            oprov["extract"] = ext
            other["provenance"] = oprov
            voice_save(other)
    return True


def _voice_actor_x_text(value: Any, most: int) -> str:
    return " ".join(str(value or "").split())[:most]


def _voice_actor_x_secs(value: Any) -> float | None:
    """90, "90.5", "1:30", "1:04:30.2" -> seconds (the lab's parse_ts)."""
    if value in (None, ""):
        return None
    try:
        parts = [float(p) for p in str(value).strip().split(":")]
    except ValueError:
        raise HTTPException(status_code=400, detail="a time reads 90, 1:30 or 1:04:30")
    while len(parts) < 3:
        parts.insert(0, 0.0)
    got = parts[0] * 3600 + parts[1] * 60 + parts[2]
    if got < 0:
        raise HTTPException(status_code=400, detail="a time cannot be negative")
    return round(got, 3)


def _voice_actor_x_new(kind: str, body: dict[str, Any]) -> dict[str, Any]:
    engine = str(body.get("engine") or "").lower()
    if engine not in ("xtts", "f5"):
        raise HTTPException(status_code=400, detail="engine is xtts or f5 - the reference is cut for one of them")
    twin = str(body.get("twin") or "")
    if twin and not (VOICE_ACTOR_X_ID.match(twin) and voice_actor_x_row(twin)):
        twin = ""
    return {"id": "vx_" + uuid.uuid4().hex[:10], "kind": kind, "state": "station", "stage": "queued",
            "progress": 0.0, "note": "", "created": time.time(), "updated": time.time(),
            "name": _voice_actor_x_text(body.get("name"), 80), "who": _voice_actor_x_text(body.get("who"), 200),
            "notes": str(body.get("notes") or "").strip()[:600], "engine": engine, "twin": twin,
            "speaker": _voice_actor_x_text(body.get("speaker"), 40), "lab_job": "", "voice_id": "",
            "error": "", "error_kind": ""}


def _voice_actor_x_enter(row: dict[str, Any]) -> None:
    with VOICE_ACTOR_X_LOCK:
        jobs = voice_actor_x_read()["jobs"]
        jobs[row["id"]] = row
        if row.get("twin") and isinstance(jobs.get(row["twin"]), dict):
            jobs[row["twin"]]["twin"] = row["id"]
        voice_actor_x_save()
    voice_actor_x_launch(row["id"])


@app.get("/api/voice-actor/extract/health")
async def voice_actor_x_health_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """What the pane may say about the road: the reference each engine listens
    to (ENGINE_REGISTRY ref_s), the lab's clean-speech floor, the cart limits."""
    require_read_auth(authorization)
    refs = {k: {"ref_s": (ENGINE_REGISTRY.get(k) or {}).get("ref_s"),
                "label": (ENGINE_REGISTRY.get(k) or {}).get("label") or k} for k in ("xtts", "f5")}
    return {"ok": True, "v": 1, "engines": refs, "ref_min_s": 10.0,
            "clips_max": VOICE_ACTOR_X_CLIPS_MAX, "join_most_s": VOICE_ACTOR_X_JOIN_MOST_S,
            "join_least_s": VOICE_ACTOR_X_JOIN_LEAST_S, "gap_s": VOICE_ACTOR_X_GAP_S,
            "user_root": voice_actor_x_user_root(), "stages": list(VOICE_ACTOR_X_STAGES)}


@app.get("/api/voice-actor/extract/sfx")
async def voice_actor_x_sfx_api(
    folder: str = "", q: str = "", video: str = "", offset: int = 0, limit: int = 40,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """A page of the clip book for the pane's browser - off the loop."""
    require_read_auth(authorization)
    folder = str(folder or "").strip()[:400]
    q = " ".join(str(q or "").split())[:120]
    if not folder and not q:
        raise HTTPException(status_code=400, detail="name a folder or type something to search for")
    try:
        return await asyncio.to_thread(voice_actor_x_browse, folder, q, str(video or ""),
                                       max(0, min(100000, int(offset))), max(1, min(80, int(limit))))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"the clip book could not be read: {exc}"[:200]) from exc


@app.post("/api/voice-actor/extract/link")
async def voice_actor_x_link_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """{url, start?, end?, name, who?, notes?, engine: xtts|f5, speaker?, twin?} - the
    studio's link road with the pane's in/out and specifics."""
    require_auth(authorization)
    body = await request.json()
    body = body if isinstance(body, dict) else {}
    url = str(body.get("url") or "").strip()[:2000]
    if not url:
        raise HTTPException(status_code=400, detail="Paste the address of a video, a post, or an audio file.")
    start, end = _voice_actor_x_secs(body.get("start")), _voice_actor_x_secs(body.get("end"))
    if start is not None and end is not None and end - start < 1.0:
        raise HTTPException(status_code=400, detail="the out point has to come at least a second after the in point")
    row = _voice_actor_x_new("link", body)
    row.update({"url": url, "start": start, "end": end,
                "range": "-".join("%g" % x for x in (start, end) if x is not None),
                "user_submitted": False, "credits": []})
    _voice_actor_x_enter(row)
    return {"ok": True, **voice_actor_x_public(row)}


@app.post("/api/voice-actor/extract/clips")
async def voice_actor_x_clips_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """{clips: [{id, start?, end?}] (1-12), name, who?, notes?, engine, speaker?, twin?} -
    the bin cart as ONE signature job: joined on the station, one lab job."""
    require_auth(authorization)
    body = await request.json()
    body = body if isinstance(body, dict) else {}
    asked = body.get("clips") if isinstance(body.get("clips"), list) else []
    if not 1 <= len(asked) <= VOICE_ACTOR_X_CLIPS_MAX:
        raise HTTPException(status_code=400, detail="a cart holds 1 to %d clips" % VOICE_ACTOR_X_CLIPS_MAX)
    clips: list[dict[str, Any]] = []
    for item in asked:
        item = item if isinstance(item, dict) else {"id": item}
        sid = str(item.get("id") or "")
        if not VOICE_ACTOR_X_SID.match(sid):
            raise HTTPException(status_code=400, detail="not a clip id: %s" % sid[:40])
        path = await asyncio.to_thread(sfx_by_id, sid)
        if path is None:
            raise HTTPException(status_code=404, detail="clip %s is not in the library any more" % sid)
        start, end = _voice_actor_x_secs(item.get("start")), _voice_actor_x_secs(item.get("end"))
        if start is not None and end is not None and end - start < 0.2:
            raise HTTPException(status_code=400, detail="%s: the out point comes before the in point" % path.stem)
        clips.append({"id": sid, "path": str(path), "name": path.stem[:120], "video": sfx_is_video(path),
                      "user": voice_actor_x_is_user(path), "where": voice_actor_x_where(path),
                      "start": start, "end": end,
                      "seconds": round(float(item.get("seconds") or 0), 2) or None})
    row = _voice_actor_x_new("cart", body)
    if not row["name"]:
        row["name"] = clips[0]["name"][:80]
    users = [c for c in clips if c["user"]]
    row.update({"clips_in": clips, "user_submitted": bool(users),
                "credits": [voice_actor_x_credit(c["path"]) for c in users]})
    _voice_actor_x_enter(row)
    return {"ok": True, **voice_actor_x_public(row)}


@app.get("/api/voice-actor/extract/jobs")
async def voice_actor_x_jobs_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """The recent submissions, newest first - so a second glass sees them too."""
    require_read_auth(authorization)
    with VOICE_ACTOR_X_LOCK:
        rows = sorted(voice_actor_x_read()["jobs"].values(), key=lambda r: -float(r.get("created") or 0))[:40]
        rows = json.loads(json.dumps(rows))
    return {"ok": True, "jobs": [{**voice_actor_x_public(r), "state": r.get("state"), "stage": r.get("stage"),
                                  "voice_id": r.get("voice_id") or "", "error": r.get("error") or ""}
                                 for r in rows]}


@app.get("/api/voice-actor/extract/jobs/{vx}")
async def voice_actor_x_job_api(vx: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """One submission. On the station (join / handoff) it answers itself; in the
    lab it asks voicelab_job() - the harvest happens THERE, as it always has -
    and stamps the voice once it lands."""
    require_read_auth(authorization)
    if not VOICE_ACTOR_X_ID.match(vx or ""):
        raise HTTPException(status_code=404, detail="No such job")
    row = voice_actor_x_row(vx)
    if row is None:
        raise HTTPException(status_code=404, detail="No such job")
    base = voice_actor_x_public(row)
    state = row.get("state")
    if state == "station":
        if vx not in VOICE_ACTOR_X_TASKS:
            voice_actor_x_update(vx, state="error", stage="error", error_kind="STATION_RESTARTED",
                                 error="The station restarted before the lab had it - retry and it runs again "
                                       "from the kept link or clips.")
            row = voice_actor_x_row(vx) or row
            state = "error"
        else:
            return {**base, "stage": row.get("stage") or "queued", "progress": float(row.get("progress") or 0),
                    "note": row.get("note") or "", "station": True, "harvested": False, "stages_done": []}
    if state == "error":
        return {**base, "stage": "error", "progress": 0.0, "harvested": False,
                "error": row.get("error") or "", "error_kind": row.get("error_kind") or "",
                "stages_done": row.get("stages_done") or []}
    if state == "done":
        return {**base, **(row.get("last") or {}), "stage": "done", "progress": 1.0, "harvested": True,
                "voice_id": row.get("voice_id") or "", "stamped": True}
    try:
        status = await voicelab_job(str(row.get("lab_job") or ""), authorization)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        voice_actor_x_update(vx, state="error", stage="error", error_kind="LAB_GONE",
                             error="The lab no longer has this job - retry and it runs again from the kept "
                                   "link or clips.")
        return await voice_actor_x_job_api(vx, authorization)
    keep = {k: status.get(k) for k in ("stages_done", "note", "title", "diarize_note", "speakers",
                                       "speaker_used", "extra_speakers", "signature_note") if status.get(k)}
    if status.get("stage") == "error":
        voice_actor_x_update(vx, state="error", stage="error", error=str(status.get("error") or "")[:300],
                             error_kind=str(status.get("error_kind") or "LAB_ERROR"), stages_done=keep.get("stages_done") or [])
        return {**status, **base, "stage": "error"}
    stamped = False
    if status.get("harvested") and status.get("voice_id"):
        stamped = voice_actor_x_stamp(vx, row, status)
        voice_actor_x_update(vx, state="done", stage="done", voice_id=str(status["voice_id"]),
                             last={**keep, "stages_done": list(VOICE_ACTOR_X_STAGES)})
    return {**status, **base, "stamped": stamped}


@app.post("/api/voice-actor/extract/jobs/{vx}/retry")
async def voice_actor_x_retry_api(vx: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Run a failed submission again from what was kept (the link and range, or
    the clips and their in/out) - a fresh lab job under the same vx."""
    require_auth(authorization)
    row = voice_actor_x_row(vx) if VOICE_ACTOR_X_ID.match(vx or "") else None
    if row is None:
        raise HTTPException(status_code=404, detail="No such job")
    if row.get("state") != "error" or vx in VOICE_ACTOR_X_TASKS:
        raise HTTPException(status_code=409, detail="only a failed job is retried")
    voice_actor_x_update(vx, state="station", stage="queued", progress=0.0, note="", error="",
                         error_kind="", lab_job="", joined=None)
    voice_actor_x_launch(vx)
    return {"ok": True, **voice_actor_x_public(voice_actor_x_row(vx) or row)}


''' + _ROUTES_OLD

EDITS = [
    ("vx-routes", _ROUTES_OLD, _ROUTES_NEW, 1),
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
    raw = path.read_bytes().decode("utf-8")
    assert "\r" not in raw, "app.py is expected LF-only"
    text = raw
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
    text = Path(target).read_bytes().decode("utf-8")
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
