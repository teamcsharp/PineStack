#!/usr/bin/env python3
"""[memdiet] THE MESSAGE VIEW'S LED LEVELS DECODE ONE CLIP AT A TIME, AND
ONLY THE FIRST TWO MINUTES OF IT.

What killed the PineTab at launch (2026-09-29 15:31, and every launch from
15:52): every audio bubble - the live one AND each of the 20 history bubbles
the Message view builds when it opens - called mvLevelsAsk(), which fetched
the WHOLE clip (up to 16 MB) and decodeAudioData()'d it, all at once, with no
queue. On Android WebView a decodeAudioData runs a MediaCodec (the
c2.mtk.mp3.decoder bursts in logcat just before each kill) in the browser
process and hands the whole PCM to the renderer, which holds it as float at
the file's own rate before resampling: tens to hundreds of MB per clip, times
twenty, inside the first seconds. lmkd: "min watermark is breached and swap
is low".

Now:
  * a queue, ONE decode at a time, newest first (the live bubble), at most
    3 waiting - an ask pushed out of the queue is forgotten, so a later ask
    (the bubble played again) is taken;
  * the first job starts on the next tick, so a history fill of twenty
    bubbles decodes at most the newest few, never all twenty;
  * only the first 2,000,000 bytes are asked for (Range) - mvLevelsCompute
    reads only 120 s anyway - and a server that answers 200 with a longer
    body is not read at all ("too long to measure here"; the meter falls
    back to the live analyser, as it already did for a failed decode).

Applies to every copy of script-page.js under <root> (desktop/renderer and
app/src/main/assets/pine-views, whichever exist - a kiosk checkout has only
the second). Copies must match before and after.

usage: edit_memdiet_levels.py --check|--apply <root>
exit 0 ready, 2 already applied, 1 anchor missing
"""
import sys
from pathlib import Path

MARK = "[memdiet-levels]"
DIRS = ("desktop/renderer", "app/src/main/assets/pine-views")

OLD = r"""  function mvLevelsAsk(sid, url) {
    mv.levels = mv.levels || Object.create(null);
    mv.levelOrder = mv.levelOrder || [];
    if (!sid || !url || mv.levels[sid]) return;
    var L = mv.levels[sid] = {ready: false, failed: ''};
    mv.levelOrder.push(sid);
    while (mv.levelOrder.length > 8) delete mv.levels[mv.levelOrder.shift()];
    var Off = root.OfflineAudioContext || root.webkitOfflineAudioContext;
    if (typeof root.fetch !== 'function' || !Off) { L.failed = 'no decoder here'; return; }
    root.fetch(stationUrl(url)).then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
      return r.arrayBuffer();
    }).then(function (buf) {
      if (!buf || buf.byteLength > 16000000) throw new Error('too large to measure');
      var ctx = new Off(1, 1, 22050);
      return new Promise(function (ok, bad) {
        var p = ctx.decodeAudioData(buf, ok, bad);
        if (p && typeof p.then === 'function') p.then(ok, bad);
      });
    }).then(function (ab) { return mvLevelsCompute(L, ab); }).then(null, function (e) {
      L.failed = String((e && e.message) || e || 'undecodable');
    });
  }
"""

NEW = r"""  /* [memdiet-levels] ONE DECODE AT A TIME, AND ONLY THE FIRST TWO MINUTES.
     Every audio bubble (and each of the twenty a history fill builds) used to
     fetch its whole clip and decodeAudioData() it at once, unqueued. On the
     tablet's WebView each decode is a MediaCodec in the browser process plus
     the whole PCM in the renderer; twenty at launch was the lowmemorykiller
     kill of 2026-09-29. Now: a queue, one at a time, newest first (the live
     bubble), three waiting at most (a dropped ask is forgotten, so a later one
     is taken), and at most MV_LV_MAX_BYTES asked for - mvLevelsCompute reads
     only 120 s. A longer body is never read: the meter falls back to the live
     analyser, as it does for any clip it cannot measure. */
  var MV_LV_MAX_BYTES = 2000000, MV_LV_WAITING = 3;
  function mvLevelsAsk(sid, url) {
    mv.levels = mv.levels || Object.create(null);
    mv.levelOrder = mv.levelOrder || [];
    mv.levelQ = mv.levelQ || [];
    if (!sid || !url || mv.levels[sid]) return;
    var L = mv.levels[sid] = {ready: false, failed: ''};
    mv.levelOrder.push(sid);
    while (mv.levelOrder.length > 8) delete mv.levels[mv.levelOrder.shift()];
    mv.levelQ.push({sid: sid, url: url, L: L});
    while (mv.levelQ.length > MV_LV_WAITING) {
      var old = mv.levelQ.shift();
      if (mv.levels[old.sid] === old.L) delete mv.levels[old.sid];
    }
    if (!mv.levelKick) mv.levelKick = setTimeout(mvLevelsNext, 0);
  }
  function mvLevelsNext() {
    mv.levelKick = 0;
    if (mv.levelBusy || !mv.levelQ || !mv.levelQ.length) return;
    var job = mv.levelQ.pop();                 /* newest first: the live bubble */
    var L = job.L;
    mv.levelBusy = job;
    var done = function () {
      if (mv.levelBusy !== job) return;        /* the guard already moved on */
      mv.levelBusy = null;
      if (mv.levelQ.length && !mv.levelKick) mv.levelKick = setTimeout(mvLevelsNext, 250);
    };
    setTimeout(function () {                   /* a fetch that never answers holds nothing up */
      if (mv.levelBusy === job) { if (!L.ready) L.failed = L.failed || 'timed out'; done(); }
    }, 30000);
    var Off = root.OfflineAudioContext || root.webkitOfflineAudioContext;
    if (typeof root.fetch !== 'function' || !Off) { L.failed = 'no decoder here'; done(); return; }
    root.fetch(stationUrl(job.url), {headers: {Range: 'bytes=0-' + (MV_LV_MAX_BYTES - 1)}}).then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
      var len = Number((r.headers && r.headers.get('content-length')) || 0);
      if (r.status !== 206 && len > MV_LV_MAX_BYTES) {
        try { if (r.body && r.body.cancel) r.body.cancel(); } catch (e) { /* not streamed */ }
        throw new Error('too long to measure here');
      }
      return r.arrayBuffer();
    }).then(function (buf) {
      if (!buf || buf.byteLength > MV_LV_MAX_BYTES + 65536) throw new Error('too long to measure here');
      var ctx = new Off(1, 1, 22050);
      return new Promise(function (ok, bad) {
        var p = ctx.decodeAudioData(buf, ok, bad);
        if (p && typeof p.then === 'function') p.then(ok, bad);
      });
    }).then(function (ab) { return mvLevelsCompute(L, ab); }).then(done, function (e) {
      L.failed = String((e && e.message) || e || 'undecodable');
      done();
    });
  }
"""


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    root = Path(sys.argv[2] if len(sys.argv) > 2 else ".")
    files = [root / d / "script-page.js" for d in DIRS if (root / d / "script-page.js").is_file()]
    if not files:
        print("%s no script-page.js under %s" % (MARK, root))
        return 1
    got = []
    for p in files:
        raw = p.read_bytes().decode("utf-8")
        got.append((p, "\r\n" in raw, raw.replace("\r\n", "\n")))
    done = [MARK in t for (_p, _c, t) in got]
    if all(done):
        print("%s already applied (%d copies)" % (MARK, len(got)))
        return 2
    if any(done):
        print("%s half applied - the copies differ" % MARK)
        return 1
    bad = ["%s: %d x the old mvLevelsAsk (want 1)" % (p, t.count(OLD)) for (p, _c, t) in got if t.count(OLD) != 1]
    if bad:
        print("%s anchor missing:\n  %s" % (MARK, "\n  ".join(bad)))
        return 1
    if mode != "--apply":
        print("%s ready (%d copies)" % (MARK, len(got)))
        return 0
    for p, crlf, t in got:
        t = t.replace(OLD, NEW)
        if crlf:
            t = t.replace("\n", "\r\n")
        tmp = p.with_name(p.name + ".memdiet-tmp")
        tmp.write_bytes(t.encode("utf-8"))
        tmp.replace(p)
    print("%s applied (%d copies)" % (MARK, len(got)))
    return 2


if __name__ == "__main__":
    sys.exit(main())
