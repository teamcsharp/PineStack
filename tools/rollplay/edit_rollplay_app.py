#!/usr/bin/env python3
"""[rollplay] the boomerang thumbnail route and its one-at-a-time maker (app.py)

GET /api/sfx/boomerang/<id>?t=<sig>[&probe=1]: a <=4 s, 240p, video-only forward-then-reversed excerpt, made lazily at nice 19 by ONE worker, never while ComfyUI is busy or in the first 180 s of a boot; cached in data/sfx_boomerangs (300 kept). Target: app.py (py_compile checked).

  python edit_rollplay_app.py --check <file> [<file> ...]   exit 0 ready / 2 applied / 1 anchor missing
  python edit_rollplay_app.py --apply <file> [<file> ...]   idempotent; resumes a half-applied file

Marker-idempotent: an edit counts as APPLIED when its whole replacement is in
the file, READY when its anchor occurs exactly once. Line endings are kept
(a CRLF file stays CRLF, an LF file LF). The write is atomic, and a .js file
must pass `node --check` (when node is on PATH) before it replaces the old
one; a .json file must parse.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

EDITS = [('B1 the boomerang route, before the phone bell routes', '@app.get("/api/sfx/ring")\nasync def sfx_ring_get(', '# [rollplay] THE BOOMERANG THUMBNAIL. "loop as a BOOMERANG: play forward,\n# then play backward to the start, then forward again" (the operator,\n# 2026-09-29, for the Message view\'s muted clip thumbnails and the popup\n# PiP when it idles). A <video> cannot run backwards smoothly - a backwards\n# currentTime walk stutters on a long-GOP MP4, worst in the tablet\'s\n# WebView - so the clip is MADE once: a <= 4 s excerpt from the poster\'s\n# point (0.5 s, else the start), 240p, video only, forward then reversed\n# ([0:v]trim,split[a][b];[b]reverse[r];[a][r]concat), h264 baseline, a\n# 12-frame GOP, faststart. Kept beside the posters, keyed by the clip id,\n# the file\'s size and mtime and a version, pruned to SFX_BOOM_KEEP files.\n#\n# THE HEAT RULE. The box overheats (#1285): one job at a time, in ONE\n# worker, under `nice -n 19`, never while ComfyUI has anything running or\n# queued (comfy_idle_live), never in the first SFX_BOOM_BOOT_S of a boot.\n# The first ask answers 202 {"making": true} and queues the clip; the page\n# plays the plain forward loop until a later ask answers the file.\nSFX_BOOM_DIR = data_path("sfx_boomerangs")\nSFX_BOOM_VERSION = 1\nSFX_BOOM_SECONDS = 4.0\nSFX_BOOM_KEEP = 300\nSFX_BOOM_BOOT_S = 180.0\n_SFX_BOOM_BORN = time.time()\n_SFX_BOOM_STATE: dict[str, str] = {}          # sid -> queued | making | failed\n_SFX_BOOM_QUEUE: list[tuple[str, Path, Path]] = []\n_SFX_BOOM_TASK: list[Any] = [None]\n\n\ndef _boom_json(obj: Any, status_code: int = 200, headers: Any = None) -> Response:\n    return Response(json.dumps(obj), status_code=status_code, headers=headers or {}, media_type="application/json")\n\n\ndef _sfx_boom_path(sid: str, sample: Path) -> Path:\n    st = sample.stat()\n    return SFX_BOOM_DIR / f"{sid}-{int(st.st_mtime)}-{st.st_size}-v{SFX_BOOM_VERSION}.mp4"\n\n\ndef _render_boomerang(source: Path, out: Path, seconds: float = SFX_BOOM_SECONDS) -> bool:\n    """[rollplay] The forward-then-reversed excerpt, video only (see above)."""\n    import shutil as _shutil\n    import subprocess\n\n    import imageio_ffmpeg\n    exe = imageio_ffmpeg.get_ffmpeg_exe()\n    nice = ["nice", "-n", "19"] if _shutil.which("nice") else []\n    part = out.with_suffix(".part.mp4")\n    graph = ("[0:v]trim=duration=%.2f,setpts=PTS-STARTPTS,fps=24,scale=-2:240:flags=bicubic,"\n             "format=yuv420p,split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0[v]" % seconds)\n    for seek in ("0.5", "0"):\n        try:\n            subprocess.run(\n                nice + [exe, "-nostdin", "-loglevel", "error", "-y", "-ss", seek, "-i", str(source),\n                        "-filter_complex", graph, "-map", "[v]", "-an",\n                        "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0", "-preset", "veryfast",\n                        "-crf", "30", "-g", "12", "-keyint_min", "12", "-sc_threshold", "0",\n                        "-movflags", "+faststart", str(part)],\n                check=True, timeout=90)\n        except Exception:\n            part.unlink(missing_ok=True)\n            continue\n        try:\n            made = part.exists() and part.stat().st_size > 1024\n        except OSError:\n            made = False\n        if made:\n            part.replace(out)\n            return True\n        part.unlink(missing_ok=True)\n    return False\n\n\ndef _sfx_boom_prune() -> None:\n    try:\n        files = sorted(SFX_BOOM_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime)\n    except OSError:\n        return\n    for old in files[:-SFX_BOOM_KEEP] if len(files) > SFX_BOOM_KEEP else []:\n        try:\n            old.unlink()\n        except OSError:\n            pass\n\n\nasync def _sfx_boom_worker() -> None:\n    """ONE worker; it waits out a busy ComfyUI and the boot window."""\n    try:\n        while _SFX_BOOM_QUEUE:\n            if time.time() - _SFX_BOOM_BORN < SFX_BOOM_BOOT_S:\n                await asyncio.sleep(15)\n                continue\n            try:\n                busy = bool((await comfy_idle_live()).get("busy"))\n            except Exception:  # noqa: BLE001\n                busy = False\n            if busy:\n                await asyncio.sleep(20)\n                continue\n            sid, sample, out = _SFX_BOOM_QUEUE.pop(0)\n            _SFX_BOOM_STATE[sid] = "making"\n            try:\n                SFX_BOOM_DIR.mkdir(parents=True, exist_ok=True)\n                ok = await asyncio.to_thread(_render_boomerang, sample, out)\n                await asyncio.to_thread(_sfx_boom_prune)\n            except Exception:  # noqa: BLE001\n                ok = False\n            if ok:\n                _SFX_BOOM_STATE.pop(sid, None)\n            else:\n                _SFX_BOOM_STATE[sid] = "failed"\n    finally:\n        _SFX_BOOM_TASK[0] = None\n\n\n@app.get("/api/sfx/boomerang/{sid}")\nasync def sfx_boomerang_api(\n    sid: str,\n    request: Request,\n    authorization: str | None = Header(default=None),\n) -> Response:\n    """[rollplay] The clip\'s boomerang thumbnail, made lazily (see above).\n    ?probe=1 answers JSON only: {ready, url} or {making}."""\n    cors = {"Access-Control-Allow-Origin": "*", "X-Content-Type-Options": "nosniff"}\n    if not re.match(r"^[a-f0-9]{16}\\Z", sid or ""):\n        return Response(status_code=404, headers=cors)\n    signature = str(request.query_params.get("t") or "")\n    expected = media_sign(sid)\n    if not (expected and hmac.compare_digest(signature, expected)):\n        require_read_auth(authorization)\n    sample = await asyncio.to_thread(sfx_by_id, sid)\n    if sample is None or not sfx_is_video(sample):\n        return _boom_json({"ready": False, "why": "not a video"}, status_code=404, headers=cors)\n    out = await asyncio.to_thread(_sfx_boom_path, sid, sample)\n    if not out.exists():\n        state = _SFX_BOOM_STATE.get(sid)\n        if state == "failed":\n            return _boom_json({"ready": False, "why": "could not be made"}, status_code=404, headers=cors)\n        if not state and len(_SFX_BOOM_QUEUE) < 40:\n            _SFX_BOOM_STATE[sid] = "queued"\n            _SFX_BOOM_QUEUE.append((sid, sample, out))\n        if _SFX_BOOM_TASK[0] is None and _SFX_BOOM_QUEUE:\n            _SFX_BOOM_TASK[0] = asyncio.create_task(_sfx_boom_worker())\n        return _boom_json({"ready": False, "making": True, "state": _SFX_BOOM_STATE.get(sid) or "queued"},\n                            status_code=202, headers=cors)\n    url = f"/api/sfx/boomerang/{sid}?t={expected}"\n    if request.query_params.get("probe"):\n        return _boom_json({"ready": True, "url": url}, headers=cors)\n    size = await asyncio.to_thread(lambda: out.stat().st_size)\n    headers = dict(cors, **{"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=86400"})\n    window = _range_slice(str(request.headers.get("range") or ""), size)\n    if window == (-1, -1):\n        headers["Content-Range"] = f"bytes */{size}"\n        return Response(status_code=416, headers=headers)\n    if window:\n        start, end = window\n        headers["Content-Range"] = f"bytes {start}-{end}/{size}"\n        return Response(await _range_once(out, start, end), status_code=206, headers=headers, media_type="video/mp4")\n    return Response(await asyncio.to_thread(out.read_bytes), headers=headers, media_type="video/mp4")\n\n\n\n@app.get("/api/sfx/ring")\nasync def sfx_ring_get(')]


def status(text):
    out = []
    for name, anchor, new in EDITS:
        if new.rstrip('\n') in text:
            out.append((name, 'applied'))
        elif anchor is None:
            out.append((name, 'ready'))
        else:
            n = text.count(anchor)
            out.append((name, 'ready' if n == 1 else 'missing (anchor x%d)' % n))
    return out


def verify(path, text):
    if path.endswith('.json'):
        json.loads(text)
        return ''
    if path.endswith('.py'):
        try:
            compile(text, path, 'exec')
        except SyntaxError as err:
            return 'SyntaxError: %s (line %s)' % (err.msg, err.lineno)
        return ''
    if path.endswith('.js') and shutil.which('node'):
        fd, tmp = tempfile.mkstemp(suffix='.js')
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as fh:
            fh.write(text)
        try:
            got = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
            return '' if got.returncode == 0 else (got.stderr or got.stdout)[-800:]
        finally:
            os.unlink(tmp)
    return ''


def one(path, apply):
    raw = open(path, 'rb').read().decode('utf-8')
    crlf = raw.count('\r\n') > raw.count('\n') // 2
    text = raw.replace('\r\n', '\n')
    st = status(text)
    for name, s in st:
        print('  %-60s %s' % (name, s))
    if any(s.startswith('missing') for _, s in st):
        print('%s: ANCHOR MISSING' % path)
        return 1
    if all(s == 'applied' for _, s in st):
        print('%s: already applied' % path)
        return 2
    if not apply:
        print('%s: ready' % path)
        return 0
    for name, anchor, new in EDITS:
        if new.rstrip('\n') in text:
            continue
        if anchor is None:
            text = text.rstrip('\n') + '\n' + new if text else new
            if not text.endswith('\n'):
                text += '\n'
        else:
            assert text.count(anchor) == 1, name
            text = text.replace(anchor, new, 1)
    assert all(s == 'applied' for _, s in status(text)), 'an edit did not land'
    bad = verify(path, text)
    if bad:
        print('%s: REFUSED - the result does not parse:\n%s' % (path, bad))
        return 1
    if crlf:
        text = text.replace('\n', '\r\n')
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix='.part')
    with os.fdopen(fd, 'wb') as fh:
        fh.write(text.encode('utf-8'))
    try:
        shutil.copymode(path, tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    print('%s: APPLIED (%s)' % (path, 'CRLF' if crlf else 'LF'))
    return 0


def main(argv):
    apply = '--apply' in argv
    paths = [a for a in argv if not a.startswith('--')]
    if not paths:
        print(__doc__)
        return 1
    rcs = [one(p, apply) for p in paths]
    return 1 if 1 in rcs else (0 if 0 in rcs else 2)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
