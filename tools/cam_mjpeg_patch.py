"""[cam-mjpeg] the desk sees the Pine Cam at full rate, like the tablet.

"when streaming the pine cam to the desktop app. make sure the performance is
optimal. It appeared to have a low FPS when I tested it. I want it also high FPS
like the tablet." The desk has no native player: it polled /api/pinelink/frame.jpg
four times a second. The tablet plays the TS door natively at 30 fps. Chromium
plays multipart MJPEG in a plain <img> at whatever rate it arrives, with no
library - so the TS door gets /live.mjpg: per viewer, one ffmpeg reads the
door's own /live.ts and re-encodes it (fps MJPEG_FPS, quality MJPEG_Q) until the
viewer leaves. Nothing runs while nobody watches, and the camera's own ffmpeg is
untouched. pine-cam.js points the desk's box at it once; the JPEG poll stands in
if it fails.

Usage (ON THE HOST): python3 tools/cam_mjpeg_patch.py --check|--apply
  (patches tools/pinelink.py and the three pine-cam.js copies)
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PL = [
    ('''        elif path == "/live.ts":
            self._live(door)
''', '''        elif path == "/live.ts":
            self._live(door)
        elif path == "/live.mjpg":                          # [cam-mjpeg]
            self._mjpeg(door)
'''),
    ('''    def _live(self, door: TsDoor) -> None:
''', '''    def _mjpeg(self, door: TsDoor) -> None:
        """[cam-mjpeg] the picture as multipart JPEG at full rate, for a page
        with no native player (the desk): one ffmpeg per viewer, reading this
        door's own TS, gone when the viewer is."""
        addr = (list(door.addrs) or ["127.0.0.1"])[0]
        src = "http://%s:%d/live.ts" % (addr, door.port)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
               "-fflags", "nobuffer", "-flags", "low_delay", "-probesize", "500000",
               "-analyzeduration", "0", "-i", src, "-an",
               "-vf", "fps=%d" % MJPEG_FPS, "-q:v", str(MJPEG_Q),
               "-f", "mpjpeg", "-boundary_tag", "pineframe", "pipe:1"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            self._reply(503, b"no ffmpeg\\n")
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=pineframe")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        who = "%s:%d" % self.client_address[:2]
        _ts_log("mjpeg client %s joined" % who)
        try:
            read = getattr(proc.stdout, "read1", proc.stdout.read)
            while True:
                chunk = read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                pass
            _ts_log("mjpeg client %s left" % who)

    def _live(self, door: TsDoor) -> None:
'''),
    ('''TS_UDP_HOST, TS_UDP_PORT = "127.0.0.1", 18081
''', '''TS_UDP_HOST, TS_UDP_PORT = "127.0.0.1", 18081
MJPEG_FPS = int(os.environ.get("PINELINK_MJPEG_FPS", "25"))     # [cam-mjpeg] the desk's picture rate
MJPEG_Q = int(os.environ.get("PINELINK_MJPEG_Q", "4"))          # ffmpeg -q:v, 2 (best) .. 31
'''),
]

JS = [
    ('''  function paintFrame() {
    var img = document.getElementById('pineCamImg');
    if (!img || !shown) return;
    /* A cache-buster, because the frame is one URL that keeps changing and
     * every layer between here and the disk would happily hold on to it. */
    img.src = base() + '/api/pinelink/frame.jpg?c=' + Date.now();
  }
''', '''  /* [cam-mjpeg] "I want it also high FPS like the tablet": a page with no
     native surface (the desk) plays the door's multipart JPEG stream in the
     same <img>, once - it paints itself at the stream's rate. The JPEG poll
     stands in when the door is down or the stream fails (retried after 5 s). */
  var mjpegFailedAt = 0;
  function mjpegUrl() {
    if (nativeOn || !tsInfo) return '';
    var u = String(tsInfo.url || '');
    if (/\\/live\\.ts/.test(u)) return u.replace(/\\/live\\.ts.*$/, '/live.mjpg');
    try {
      var host = new URL(base() || root.location.href).hostname;
      return host ? 'http://' + host + ':' + tsInfo.port + '/live.mjpg' : '';
    } catch (e) { return ''; }
  }
  function mjpegStop(img) {
    if (img && img.__mjpeg) { img.__mjpeg = ''; try { img.removeAttribute('src'); } catch (e) { /* gone */ } }
  }
  function paintFrame() {
    var img = document.getElementById('pineCamImg');
    if (!img || !shown) return;
    var m = mjpegUrl();
    if (m && Date.now() - mjpegFailedAt > 5000) {
      if (img.__mjpeg !== m) {
        img.__mjpeg = m;
        img.onerror = function () { mjpegFailedAt = Date.now(); img.__mjpeg = ''; };
        img.src = m + '?c=' + Date.now();
      }
      return;                                /* the stream paints itself */
    }
    img.__mjpeg = '';
    /* A cache-buster, because the frame is one URL that keeps changing and
     * every layer between here and the disk would happily hold on to it. */
    img.src = base() + '/api/pinelink/frame.jpg?c=' + Date.now();
  }
'''),
    ('''    shown = false;
    if (box) vcrBox(false);                /* [vcrfx] picture -> line -> dot, then hidden */
''', '''    shown = false;
    mjpegStop(document.getElementById('pineCamImg'));   /* [cam-mjpeg] the stream goes with the box */
    if (box) vcrBox(false);                /* [vcrfx] picture -> line -> dot, then hidden */
'''),
]

PAGES = [ROOT + "/desktop/renderer/pine-cam.js", ROOT + "/app/src/main/assets/pine-views/pine-cam.js"]


def patch(path, edits, mode, is_py=False):
    src = open(path, encoding="utf-8").read()
    if "[cam-mjpeg]" in src:
        print(path + ": APPLIED")
        return
    out = src
    for old, new in edits:
        n = out.count(old)
        assert n == 1, "%s: anchor %r found %d" % (path, old[:40], n)
        out = out.replace(old, new)
    if is_py:
        ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/%s.bak-cam-mjpeg" % os.path.basename(path))
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    mode = sys.argv[1]
    patch(ROOT + "/tools/pinelink.py", PL, mode, is_py=True)
    for p in PAGES:
        patch(p, JS, mode)
