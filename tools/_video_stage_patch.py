"""#1253/#1263: the DJ's videos on the tune page, and the stings in the car.

Three separate gaps, found together:

1. THE MIXER DROPPED EVERY SFX. `_stream_clip_path` only ever resolved
   "/media/<key>" - the spoken-clip shape. Stings are served from
   "/sfx/<id>", so every sound effect, and every video sting's audio, was
   silently skipped by the car stream. The SFX guy exists to fill dead
   air; none of it has ever reached the road.

2. THE VIDEO SET WAS PANEL-ONLY. #1263 already flags a clip with a
   picture (`video: true`) and the CONTROL PANEL opens a little CRT for
   it (djVideoTv). The tune page - the one in the car - never had one, so
   the ComfyUI gallery just carried on underneath a video nobody could
   see.

3. AND THE PICTURE HAS TO WAIT FOR THE SOUND. The stream deliberately
   runs behind live: a listener is handed ~30 s of burst so they can ride
   out a stall. Showing the video at the instant the SERVER says it aired
   would put the picture half a minute ahead of the audio in the car.
   The page already knows its own lag exactly - `buffered.end -
   currentTime` IS the audio it has received but not yet played, which is
   precisely how far behind live it is - so the set opens that much
   later, and the picture lands on the sound.
"""
import pathlib

p = pathlib.Path("app.py")
src = p.read_text()
orig = src


def sub(old, new, why):
    global src
    assert src.count(old) == 1, f"anchor {why}: {src.count(old)}"
    src = src.replace(old, new, 1)


# ==========================================================================
# 1. the mixer learns to resolve a sting
# ==========================================================================
sub(
    '''def _stream_clip_path(url: str) -> str:
    """The local file behind a voice clip's URL, or "".

    The feed hands out "/media/<key>?t=<signature>"; the key is the file
    name under VOICE_MEDIA_DIR. Anything that is not exactly that shape
    is refused rather than resolved - this runs off a mixer thread with
    no request context, so it must not be a road to arbitrary paths.
    """
    try:
        raw = str(url or "").split("?", 1)[0]
        if not raw.startswith("/media/"):
            return ""
        key = raw[len("/media/"):]
        if not MEDIA_KEY_SHAPE.match(key):
            return ""
        path = VOICE_MEDIA_DIR / key
        return str(path) if path.is_file() else ""
    except Exception:  # noqa: BLE001
        return ""''',
    '''_STREAM_SFX_CACHE: dict[str, str] = {}


def _stream_clip_path(url: str) -> str:
    """The local file behind a page-feed clip URL, or "".

    TWO shapes, and for a long time this knew only the first:

      /media/<32hex>.<ext>  a spoken clip, under VOICE_MEDIA_DIR
      /sfx/<16hex>          a sting, resolved through the sample index

    Missing the second meant the car stream silently skipped EVERY sound
    effect the station played - the SFX guy fills dead air, and none of
    it reached the road. Anything that is not exactly one of these two
    shapes is refused rather than resolved: this runs off a mixer thread
    with no request context, so it must not become a road to arbitrary
    paths.
    """
    try:
        raw = str(url or "").split("?", 1)[0]
        if raw.startswith("/media/"):
            key = raw[len("/media/"):]
            if not MEDIA_KEY_SHAPE.match(key):
                return ""
            path = VOICE_MEDIA_DIR / key
            return str(path) if path.is_file() else ""
        if raw.startswith("/sfx/"):
            key = raw[len("/sfx/"):]
            if not re.fullmatch(r"[a-f0-9]{16}", key):
                return ""
            # Memoised: the snapshot runs four times a second and the id
            # map is rebuilt whenever the pool changes, so this must not
            # become a walk on the mixer thread.
            got = _STREAM_SFX_CACHE.get(key)
            if got is None:
                found = sfx_by_id(key)
                got = str(found) if found is not None else ""
                if len(_STREAM_SFX_CACHE) > 512:
                    _STREAM_SFX_CACHE.clear()
                _STREAM_SFX_CACHE[key] = got
            return got if got and Path(got).is_file() else ""
        return ""
    except Exception:  # noqa: BLE001
        return ""''',
    "clip path")

# the snapshot carries the sting flag through
sub(
    '''            clips.append({"key": f"{ts}|{clip.get('url')}",
                          "air_at": air / 1000.0,
                          "path": path, "length": length})''',
    '''            _u = str(clip.get("url") or "")
            clips.append({"key": f"{ts}|{clip.get('url')}",
                          "air_at": air / 1000.0,
                          "path": path, "length": length,
                          # A sting is punctuation under the DJ, not a
                          # line - it is mixed a little below the voice
                          # so a hot sample cannot out-shout the show
                          # (the same intent as sfx_levelled on the
                          # HTTP road, without its decode-to-wav).
                          "sfx": _u.startswith("/sfx/")})''',
    "snapshot sfx flag")


# ==========================================================================
# 2. the video feed the page can afford to poll
# ==========================================================================
sub(
    '@app.get("/api/dj/reacts")',
    '''@app.get("/api/dj/video")
async def dj_video_now(
    t: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """The clip with a PICTURE that is on air, or about to be (#1263).

    Deliberately tiny and deliberately separate from /api/dj/voice. The
    stream road does not pull the voice feed at all - that feed announces
    clips and the page then DOWNLOADS them, which is megabytes of audio a
    stream listener never plays. This carries no audio and no queue: a
    couple of hundred bytes saying which picture is up and when, cheap
    enough for a car to ask every couple of seconds.

    `broadcast_ms` is the station's honest on-air instant. The page is
    responsible for holding it back by its own buffer depth, because a
    stream listener is deliberately behind live and the picture has to
    land on the sound.
    """
    require_listen_auth(t, authorization)
    now_ms = int(time.time() * 1000)
    out: list[dict[str, Any]] = []
    try:
        cut = int(_RADIO.get("voice_cut_ms") or 0)
        for clip in list(_RADIO.get("voice_clips") or [])[-40:]:
            if not clip.get("video"):
                continue
            ts = int(clip.get("ts") or 0)
            if ts <= cut:
                continue
            air = int(clip.get("broadcast_ms")
                      or ts + VOICE_BROADCAST_LEAD_MS)
            secs = float(clip.get("seconds") or 0)
            # Everything from a little before now to a couple of minutes
            # back: a listener thirty seconds behind live still needs the
            # one that "finished" twenty seconds ago.
            if now_ms - (air + int(secs * 1000)) > 180000:
                continue
            out.append({
                "url": str(clip.get("url") or ""),
                "name": str(clip.get("sting") or clip.get("text") or ""),
                "broadcast_ms": air,
                "seconds": round(secs, 2),
            })
    except Exception:  # noqa: BLE001
        pass
    return {"server_ms": now_ms, "videos": out[-6:]}


@app.get("/api/dj/reacts")''',
    "video endpoint")

sub(
    '_PUBLIC_GET = {"/healthz", "/api/dj", "/api/dj/voice", "/api/dj/reacts",',
    '_PUBLIC_GET = {"/healthz", "/api/dj", "/api/dj/voice", "/api/dj/reacts",\n'
    '               # #1263: which picture is up. Tiny, and audio-free.\n'
    '               "/api/dj/video",',
    "allowlist video")

# /sfx/ is already on the prefix list (added as #1353b by another pass).

assert src != orig
p.write_text(src)
print("server side: stings in the mix, /api/dj/video, allowlist")
