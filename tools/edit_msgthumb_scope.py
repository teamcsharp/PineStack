#!/usr/bin/env python3
"""[msgthumb] pinelive-scope.js: vizDraw honours state.transparent (clears instead of painting its
#05080b box; Lime slats cut rather than painted) so the Message view's record visualizer sits on
the bubble. PineLive's own audiograph never sets it: unchanged.

Targets: desktop/renderer/pinelive-scope.js and app/src/main/assets/pine-views/pinelive-scope.js.

  python edit_msgthumb_scope.py --check <file>   exit 0 ready / 2 already applied / 1 missing (prints which)
  python edit_msgthumb_scope.py --apply <file>
Marker-idempotent; CRLF-aware (normalised to LF to match, written back as found);
all anchors must be present exactly once or nothing is written.
"""
import os
import sys
import tempfile

NEEDS = []
EDITS = [('S1', 'after', '    var vz = state.vz || (state.vz = {style: 0, level: [], hold: [], holdAt: [], at: 0, named: 0});\n', "    vz.clear = !!state.transparent;   /* [msgthumb] a caller's transparent canvas */\n", 'vz.clear = !!state.transparent;   /* [msgthumb]'), ('S2', 'replace', "      vctx.globalAlpha = 1;\n      vctx.fillStyle = '#05080b';\n      vctx.fillRect(0, 0, cw, ch);\n", "      vctx.globalAlpha = 1;\n      if (vz.clear) vctx.clearRect(0, 0, cw, ch);   /* [msgthumb] the marks only */\n      else { vctx.fillStyle = '#05080b'; vctx.fillRect(0, 0, cw, ch); }\n", 'if (vz.clear) vctx.clearRect(0, 0, cw, ch);   /* [msgthumb]'), ('S3', 'replace', "          vctx.fillStyle = '#05080b';\n          for (y = mid - gap / 2 - pitch * Math.floor(mid / pitch); y < ch; y += pitch) vctx.fillRect(0, y, cw, gap);\n", "          vctx.fillStyle = '#05080b';\n          if (vz.clear) vctx.globalCompositeOperation = 'destination-out';   /* [msgthumb] slats cut, not painted */\n          for (y = mid - gap / 2 - pitch * Math.floor(mid / pitch); y < ch; y += pitch) vctx.fillRect(0, y, cw, gap);\n          vctx.globalCompositeOperation = 'source-over';\n", 'slats cut, not painted */')]


def state(text):
    done, ready, missing = [], [], []
    for name, kind, anchor, new, mark in EDITS:
        if mark in text:
            done.append(name)
        elif text.count(anchor) == 1:
            ready.append(name)
        else:
            missing.append('%s (anchor x%d)' % (name, text.count(anchor)))
    return done, ready, missing


def main(argv):
    apply = '--apply' in argv
    paths = [a for a in argv if not a.startswith('--')]
    if len(paths) != 1:
        print(__doc__)
        return 1
    path = paths[0]
    raw = open(path, 'rb').read().decode('utf-8')
    crlf = '\r\n' in raw
    text = raw.replace('\r\n', '\n') if crlf else raw
    for need in NEEDS:
        if need not in text:
            print('MISSING: needs %s applied first' % need)
            return 1
    done, ready, missing = state(text)
    if not ready and not missing:
        print('already applied (%s)' % ', '.join(done))
        return 2
    if missing:
        print('MISSING: ' + ', '.join(missing))
        return 1
    if done:
        print('PARTIAL: applied %s, ready %s - refusing' % (done, ready))
        return 1
    if not apply:
        print('ready: ' + ', '.join(ready))
        return 0
    for name, kind, anchor, new, mark in EDITS:
        assert text.count(anchor) == 1, name
        if kind == 'before':
            text = text.replace(anchor, new + anchor)
        elif kind == 'after':
            text = text.replace(anchor, anchor + new)
        else:
            text = text.replace(anchor, new)
        assert mark in text, name
    done, ready, missing = state(text)
    assert not ready and not missing, (ready, missing)
    out = text.replace('\n', '\r\n') if crlf else text
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix='.part')
    with os.fdopen(fd, 'wb') as fh:
        fh.write(out.encode('utf-8'))
    os.replace(tmp, path)
    print('APPLIED %d edits (%s)' % (len(EDITS), 'CRLF' if crlf else 'LF'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
