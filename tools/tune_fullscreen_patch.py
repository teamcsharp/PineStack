"""[tune-fullscreen] the listener page (the Tailscale stream): double-click or
double-tap a video or a popup to go full screen, the same again to go back.

"Also on the Tail Scale stream, allow a user to double click / tap a video /
popup to go in fullscreen and to do to the same to go back to windowed mode."

Usage (ON THE HOST): python3 tools/tune_fullscreen_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

ANCHOR = '''<script src="/tune-messenger/tune-messenger.js" defer></script>
</body>
</html>
"""'''

NEW = '''<script src="/tune-messenger/tune-messenger.js" defer></script>
<!-- [tune-fullscreen] "allow a user to double click / tap a video / popup to
     go in fullscreen and to do the same to go back to windowed mode." One
     listener for the page: a double click, or two taps inside 320 ms and
     30 px, on a video or a popup toggles it in and out of full screen. iOS
     Safari can only full-screen a <video> (webkitEnterFullscreen), so a popup
     there takes the page's own full-bleed class instead. Controls, links and
     fields keep their own taps. -->
<style>
.pine-fs-bleed { position: fixed !important; inset: 0 !important; width: 100vw !important;
  height: 100vh !important; max-width: none !important; max-height: none !important;
  margin: 0 !important; z-index: 2147483600 !important; background: #000 !important;
  border-radius: 0 !important; }
.pine-fs-bleed video, .pine-fs-bleed img { width: 100% !important; height: 100% !important;
  object-fit: contain !important; }
video, [role=dialog], .sfx-tv, .sfx-tv-screen, [class*=popup], [class*=lightbox],
[class*=modal], [class*=stage] { touch-action: manipulation; }
</style>
<script>
(function () {
  "use strict";
  var POPUP = '[role=dialog], .sfx-tv, [class*=popup], [class*=lightbox], [class*=modal], '
    + '[class*=stage], [class*=viewer], [class*=pip]';
  var SKIP = 'button, a, input, select, textarea, label, [role=button], [role=slider], '
    + '[contenteditable=true], .pine-fs-skip';
  function fsEl() {
    return document.fullscreenElement || document.webkitFullscreenElement || null;
  }
  function target(node) {
    if (!node || !node.closest || node.closest(SKIP)) return null;
    var v = node.closest('video');
    if (v) return v;
    var p = node.closest(POPUP);
    if (p && p !== document.body && p !== document.documentElement) return p;
    return null;
  }
  var bled = null;
  function unbleed() {
    if (bled) { bled.classList.remove('pine-fs-bleed'); bled = null; }
  }
  function toggle(el) {
    if (fsEl()) {
      try { (document.exitFullscreen || document.webkitExitFullscreen).call(document); } catch (e) { /* stays */ }
      return;
    }
    if (bled) { unbleed(); return; }
    var req = el.requestFullscreen || el.webkitRequestFullscreen;
    if (req) {
      try {
        var got = req.call(el);
        if (got && got.catch) got.catch(function () { bleed(el); });
        return;
      } catch (e) { /* the fallbacks below */ }
    }
    if (el.tagName === 'VIDEO' && el.webkitEnterFullscreen) {
      try { el.webkitEnterFullscreen(); return; } catch (e) { /* the page's own bleed */ }
    }
    bleed(el);
  }
  function bleed(el) {
    unbleed();
    bled = el;
    el.classList.add('pine-fs-bleed');
  }
  document.addEventListener('dblclick', function (ev) {
    var el = fsEl() || bled || target(ev.target);
    if (!el) return;
    ev.preventDefault();
    toggle(el);
  }, true);
  var lastTap = null;
  document.addEventListener('touchend', function (ev) {
    if (ev.touches && ev.touches.length) return;
    var t = ev.changedTouches && ev.changedTouches[0];
    if (!t) return;
    var el = fsEl() || bled || target(ev.target);
    var now = Date.now();
    if (el && lastTap && lastTap.el === el && now - lastTap.at < 320
        && Math.abs(t.clientX - lastTap.x) < 30 && Math.abs(t.clientY - lastTap.y) < 30) {
      lastTap = null;
      ev.preventDefault();
      toggle(el);
      return;
    }
    lastTap = el ? {el: el, at: now, x: t.clientX, y: t.clientY} : null;
  }, {capture: true, passive: false});
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && bled) unbleed();
  });
}());
</script>
</body>
</html>
"""'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if "[tune-fullscreen]" in src:
        print(path + ": APPLIED")
        return
    assert src.count(ANCHOR) == 1, "anchor found %d times" % src.count(ANCHOR)
    out = src.replace(ANCHOR, NEW)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/app.py.bak-tune-fullscreen")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
