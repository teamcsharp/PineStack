#!/usr/bin/env python3
"""[supercut-gallery] The marquee's tiles are the supercut videos: a poster frame each, a tap plays it. 2026-10-06.

"I want these scrolling pieces of media at the top to be the videos in a slideshow gallery. So when I tap on
them I'm able to play the videos of each and every one of the supercuts made so far." (the operator)

Edits:
  sfx_supercut_archive.py   decorate() adds poster_url beside video_url; poster(identifier) makes one JPEG frame
                            of the archived MP4 once (posters/<id>.jpg, imageio's ffmpeg, tmp + rename) and keeps it.
  sfx_supercut.py           GET /api/sfx/supercut/archive/{identifier}/poster - signed like the video, else read auth.
  desktop/renderer/supercut-review.js (+ the tablet copy)
                            a tile carries its poster frame with a play mark; a tap opens the player under the
                            marquee (the MP4 with controls, playing at once; a top-right X and Escape close it).
  desktop/renderer/supercut-review.css (+ the tablet copy)   the frame, the mark, the player.

Usage:  supercut_gallery_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        supercut_gallery_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

DECORATE_OLD = '''            value['video_url'] = '/api/sfx/supercut/archive/' + value['id'] + '/video'
            if signature:
                value['video_url'] += '?t=' + signature
        return value
'''
DECORATE_NEW = '''            value['video_url'] = '/api/sfx/supercut/archive/' + value['id'] + '/video'
            if signature:
                value['video_url'] += '?t=' + signature
            value['poster_url'] = '/api/sfx/supercut/archive/' + value['id'] + '/poster'    # [supercut-gallery] the tile's frame
            if signature:
                value['poster_url'] += '?t=' + signature
        return value
'''
POSTER_OLD = '''    def reuse(self, identifier):
'''
POSTER_NEW = '''    def poster(self, identifier):
        """[supercut-gallery] One frame of the archived MP4 as a JPEG, made once and kept beside the archive
        (posters/<id>.jpg): the studio's tiles are these. A cut with no video has none (ValueError)."""
        video = self.video(identifier)
        out = self.root / 'posters' / (self.identity(identifier) + '.jpg')
        try:
            if out.is_file() and out.stat().st_size > 0 and out.stat().st_mtime >= video.stat().st_mtime:
                return out
        except OSError:
            pass
        out.parent.mkdir(parents=True, exist_ok=True)
        make = self.host.get('poster_make')
        if not callable(make):
            make = poster_frame
        make(video, out)
        if not (out.is_file() and out.stat().st_size > 0):
            raise ValueError('The poster frame could not be made')
        return out

    def reuse(self, identifier):
'''
FRAME_OLD = '''class SupercutArchive:
'''
FRAME_NEW = '''def poster_frame(video: Path, out: Path, at: float = 1.0, width: int = 480) -> Path:
    """[supercut-gallery] imageio's bundled ffmpeg writes one scaled frame of the video; tmp + rename."""
    import subprocess
    import imageio_ffmpeg
    tmp = out.with_name(out.stem + '.tmp.jpg')
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', '-ss', str(max(0.0, float(at))),
           '-i', str(video), '-frames:v', '1', '-vf', 'scale=%d:-2' % int(width), '-q:v', '4', str(tmp)]
    subprocess.run(cmd, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    tmp.replace(out)
    return out


class SupercutArchive:
'''

ROUTE_OLD = '''    @app.post('/api/sfx/supercut/archive/{identifier}/reuse')
'''
ROUTE_NEW = '''    @app.get('/api/sfx/supercut/archive/{identifier}/poster')
    async def archive_poster(identifier: str, request: Request, authorization: str | None = Header(default=None)):
        """[supercut-gallery] the tile's frame: one JPEG of the archived MP4, made once and kept."""
        from fastapi.responses import FileResponse
        sign = host.get('media_sign')
        signature = str(sign(identifier)) if callable(sign) else ''
        if not (signature and hmac.compare_digest(str(request.query_params.get('t') or ''), signature)):
            host['require_read_auth'](authorization)
        try:
            path = await asyncio.to_thread(runtime.archive.poster, identifier)
            return FileResponse(path, media_type='image/jpeg',
                                headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=86400'})
        except Exception as exc:   # noqa: BLE001 - a frame that cannot be made is a 404 on the tile, never a 500
            raise HTTPException(404, str(exc)[:200]) from exc

    @app.post('/api/sfx/supercut/archive/{identifier}/reuse')
'''

CARD_OLD = '''      var view = make('button', 'psc-marquee-view'); view.type = 'button'; view.setAttribute('aria-label', 'View ' + (row.product || row.title || 'supercut'));
      var when = new Date(Number(row.created_at || 0) * 1000);
      view.append(make('b', '', row.product || row.title || 'Supercut'),
        make('span', '', Number(row.seconds || 0).toFixed(1) + 's' + (row.kind === 'video' ? ' video' : ' audio') + ' - ' + when.toLocaleDateString([], {month: 'numeric', day: 'numeric'}) + ' ' + when.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})));
      view.addEventListener('click', function () { marqueeSelected = row.id; marqueeMark(); marqueeHold = Date.now() + 12000; loadArchive(row.id); });
'''
CARD_NEW = '''      var view = make('button', 'psc-marquee-view'); view.type = 'button'; view.setAttribute('aria-label', 'Play ' + (row.product || row.title || 'supercut'));
      view.title = 'Play this supercut';
      var when = new Date(Number(row.created_at || 0) * 1000);
      /* [supercut-gallery] the tile is the video: its poster frame with a play mark; a tap plays it in the player under the marquee */
      if (row.poster_url) {
        var frame = make('span', 'psc-marquee-frame'); var poster = make('img', 'psc-marquee-poster'); poster.alt = ''; poster.loading = 'lazy'; poster.src = url(row.poster_url);
        poster.addEventListener('error', function () { frame.classList.add('no-poster'); });
        var mark = make('span', 'psc-marquee-play'); mark.innerHTML = (root.pineIcon ? root.pineIcon('c:play--filled') : ''); if (!mark.innerHTML) mark.textContent = 'Play';
        frame.append(poster, mark); view.appendChild(frame);
      }
      view.append(make('b', '', row.product || row.title || 'Supercut'),
        make('span', '', Number(row.seconds || 0).toFixed(1) + 's' + (row.kind === 'video' ? ' video' : ' audio') + ' - ' + when.toLocaleDateString([], {month: 'numeric', day: 'numeric'}) + ' ' + when.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})));
      view.addEventListener('click', function () { marqueeSelected = row.id; marqueeMark(); marqueeHold = Date.now() + 12000; playArchive(row.id); loadArchive(row.id); });
'''
PLAYER_OLD = '''    function marqueeMark() {'''
PLAYER_NEW = '''    /* [supercut-gallery] THE PLAYER. "I want these scrolling pieces of media at the top to be the videos in a slideshow
       gallery. So when I tap on them I'm able to play the videos of each and every one of the supercuts made so far."
       One player, right under the marquee, opened by a tile: the supercut's own MP4 (its audio when an older cut has
       no video), with controls, playing at once because a hand asked for it; a top-right X and Escape close it. */
    var player = null, playerVideo = null;
    function closePlayer() {
      if (!player) return; stop(playerVideo); playerVideo = null; player.remove(); player = null; marqueeHold = Date.now() + 1500;
    }
    function openPlayer(full) {
      closePlayer();
      player = make('div', 'psc-player'); player.setAttribute('role', 'dialog'); player.setAttribute('aria-label', 'Supercut player');
      var head = make('div', 'psc-player-head');
      head.append(make('b', '', full.title || full.product || 'Supercut'),
        make('span', 'psc-hint', Number(full.seconds || 0).toFixed(1) + ' seconds' + (full.video_url ? '' : ' - audio only, this cut has no video')));
      var x = make('button', 'psc-player-close', 'X'); x.type = 'button'; x.title = 'Close the player'; x.setAttribute('aria-label', 'Close the player');
      x.addEventListener('click', closePlayer); head.appendChild(x); player.appendChild(head);
      if (typeof root.pineCloseX === 'function') { try { root.pineCloseX(player, closePlayer, {label: 'Close the player'}); x.style.display = 'none'; } catch (e) { /* the button stands */ } }
      playerVideo = make(full.video_url ? 'video' : 'audio', 'psc-player-video'); playerVideo.controls = true; playerVideo.autoplay = true; playerVideo.playsInline = true; playerVideo.preload = 'auto';
      playerVideo.src = url(full.video_url || full.audio_url || '/api/sfx/supercut/archive/' + encodeURIComponent(full.id) + '/audio');
      player.appendChild(playerVideo);
      marquee.parentNode.insertBefore(player, marquee.nextSibling);
      try { var going = playerVideo.play(); if (going && going.catch) going.catch(function () { /* the controls are there */ }); } catch (e) { /* the controls are there */ }
    }
    function playArchive(id) {
      return get('/api/sfx/supercut/archive/' + encodeURIComponent(id)).then(function (full) { if (!dead) openPlayer(full); }).catch(function (e) { say(e.message || e); });
    }
    panel.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && player) { ev.stopPropagation(); closePlayer(); } });
    function marqueeMark() {'''
NOTE_OLD = ''' supercuts made so far - tap one to view it, or reuse its prompt' '''
NOTE_NEW = ''' supercuts made so far - tap one to play it, or reuse its prompt' '''
DISPOSE_OLD = '''stop(audio); panel.remove();'''
DISPOSE_NEW = '''stop(audio); closePlayer(); panel.remove();'''

CSS_OLD = '''body.pine-pip .psc-marquee-card{width:150px}
'''
CSS_NEW = '''body.pine-pip .psc-marquee-card{width:150px}
/* [supercut-gallery] the tile is the video: a poster frame with a play mark; the player sits under the marquee */
.psc-marquee-frame{position:relative;display:block;width:100%;aspect-ratio:16/9;border-radius:4px;overflow:hidden;background:#000}
.psc-marquee-poster{display:block;width:100%;height:100%;object-fit:cover}
.psc-marquee-frame.no-poster .psc-marquee-poster{visibility:hidden}
.psc-marquee-play{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);display:flex;align-items:center;justify-content:center;width:34px;height:34px;border-radius:50%;background:rgba(8,18,22,.72);color:#8de1ed;font:600 11px system-ui;pointer-events:none}
.psc-marquee-play svg{width:18px;height:18px;fill:currentColor}
.psc-marquee-view:hover .psc-marquee-play,.psc-marquee-view:focus-visible .psc-marquee-play{background:rgba(141,225,237,.9);color:#081216}
.psc-player{position:relative;display:flex;flex-direction:column;gap:6px;padding:8px;border:1px solid #67c7d1;border-radius:7px;background:#0b1419}
.psc-player-head{display:flex;align-items:center;gap:8px;min-width:0;padding-right:40px}.psc-player-head b{color:#8de1ed;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.psc-player-close{position:absolute;right:8px;top:8px;width:30px;height:30px;border:1px solid #45616b;border-radius:6px;background:#18242a;color:#d4e6eb;font:600 14px system-ui;cursor:pointer}
.psc-player-video{width:100%;max-height:52vh;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:4px}
audio.psc-player-video{aspect-ratio:auto;min-height:40px}
'''

JS_EDITS = [
    ("the tile carries its poster frame and plays on a tap", CARD_OLD, CARD_NEW, 1),
    ("the player under the marquee", PLAYER_OLD, PLAYER_NEW, 1),
    ("the note says play", NOTE_OLD, NOTE_NEW, 1),
    ("dispose closes the player", DISPOSE_OLD, DISPOSE_NEW, 1),
]
CSS_EDITS = [("the frame, the mark and the player", CSS_OLD, CSS_NEW, 1)]

EDITS = {
    "sfx_supercut_archive.py": [
        ("decorate() adds poster_url", DECORATE_OLD, DECORATE_NEW, 1),
        ("poster_frame(): one frame through imageio's ffmpeg", FRAME_OLD, FRAME_NEW, 1),
        ("SupercutArchive.poster(): made once, kept", POSTER_OLD, POSTER_NEW, 1),
    ],
    "sfx_supercut.py": [
        ("GET /api/sfx/supercut/archive/{identifier}/poster", ROUTE_OLD, ROUTE_NEW, 1),
    ],
    "desktop/renderer/supercut-review.js": JS_EDITS,
    "app/src/main/assets/pine-views/supercut-review.js": JS_EDITS,
    "desktop/renderer/supercut-review.css": CSS_EDITS,
    "app/src/main/assets/pine-views/supercut-review.css": CSS_EDITS,
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            tag = ("%s: %s" % (name.rsplit("/", 1)[-1], label))[:78]
            if text.count(new) >= want:
                print("%-78s applied" % tag)
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % tag)
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (tag, n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".scgallery.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
